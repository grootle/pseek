import os
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from itertools import islice
from pathlib import Path
from threading import RLock

from ...utils import add_metric, get_path_suffix
from ..archive import ARCHIVE_EXTS
from ..parser import TermNode, parse_query_expression
from ..walk import walk
from .search import search_content, search_file_and_dir


def should_skip(config, p: Path, file_ext: str, p_size: int) -> bool:
    """
    Check whether the file/directory should be skipped based on various filters.
    Returns True if the path should be skipped.
    """
    return (config.ext and file_ext not in config.ext) \
        or (config.exclude_ext and file_ext in config.exclude_ext) \
        or (config.size and (p.is_dir() or not any(  # .stat().st_size doesn't give actual size of dir.
                                                     # To measure the actual size,
                                                     # total size of all files inside it must be calculated,
                                                     # which is time-consuming
            minimum <= p_size <= maximum
            for minimum, maximum in config.size
        )))


def process_candidate(item, config, pattern, binary_pattern,
                      matches, metrics, result_queue, result_lock):
    p, metric_only = item

    # Dir metrics must be added before should_skip,
    # as it can influence these metrics
    if config.stats and p.is_dir():
        add_metric(
            metrics,
            result_queue,
            'directories_scanned',
            str(p),
            result_lock
        )

    if metric_only:
        return

    try:
        p_ext = get_path_suffix(p)
        # Path.state follows symlinks, so we use lstate here
        p_size = p.lstat().st_size
    except OSError:
        return

    if should_skip(config, p, p_ext, p_size):
        return

    if config.stats:
        path_str = str(p)

        if (config.file or config.content) and p.is_file():
            add_metric(
                metrics,
                result_queue,
                'files_scanned',
                path_str,
                result_lock
            )

        if config.archive and p_ext in ARCHIVE_EXTS:
            add_metric(
                metrics,
                result_queue,
                'archives_scanned',
                (path_str,),
                result_lock
            )

    # Search for files and directories if requested
    if config.file or config.directory:
        search_file_and_dir(
            config,
            matches,
            pattern,
            p,
            p_ext,
            metrics,
            result_queue,
            result_lock
        )

    # Search for content inside files if requested
    # Avoid empty files
    if config.content and not p.is_symlink() \
        and p.is_file() and p_size != 0:
        search_content(
            config,
            matches,
            pattern,
            binary_pattern,
            p,
            p_ext,
            metrics,
            result_queue,
            result_lock
        )


def batched(iterable, size):
    # Convert iterable to iterator to prevent
    # islice from creating identical batches.
    # Example of using iterable:
    # items = [1, 2, 3, 4, 5, 6]
    # list(islice(items, 3)) -> [1, 2, 3]
    # list(islice(items, 3)) -> Again [1, 2, 3]!
    iterator = iter(iterable)

    # If no elements remain, the batch becomes [],
    # which causes while loop to terminate
    while batch := list(islice(iterator, size)):
        yield batch


def process_batch(items, *args):
    for item in items:
        process_candidate(item, *args)


def seek(config, result_queue=None) -> dict:
    """Main search function"""
    pattern = parse_query_expression(config)
    # If expression is simple and is a single TermNode, we can use binary pattern
    binary_pattern = None
    if config.content and isinstance(pattern, TermNode):
        binary_pattern = pattern.get_binary_pattern()

    matches = {
        'file': [],
        'directory': [],
        'content': []
    }
    metrics = defaultdict(set)
    result_lock = RLock()

    workers = config.threads or (os.cpu_count() or 1)

    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix='pseek'
    ) as executor:
        pending = set()

        for batch in batched(walk(config), 16):
            pending.add(
                executor.submit(
                    process_batch,
                    batch,
                    config,
                    pattern,
                    binary_pattern,
                    matches,
                    metrics,
                    result_queue,
                    result_lock
                )
            )

            # Limit queued work to avoid excessive memory usage
            # Using workers as max number of pending items
            if len(pending) >= workers:
                done, pending = wait(
                    pending,
                    return_when=FIRST_COMPLETED
                )

                # Don't ignore exceptions. If an exception occurs, re-raise it in main thread
                for future in done:
                    future.result()

        # Wait for workers that haven't finished their work yet
        for future in pending:
            future.result()

    return matches, metrics
