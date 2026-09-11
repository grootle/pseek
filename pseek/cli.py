import click
from .searcher import seek
from .utils import check_rar_backend
from .structs import SearchConfig
from multiprocessing import Process, Queue
from queue import Empty
from collections import defaultdict
import time


def merge_matches(matches: list[tuple[int, int]]):
    """Merge overlapping matches (for example, if one match was inside another match)"""
    merged = []
    for start, end in matches:
        if not merged or start > merged[-1][1]:  # No overlap
            merged.append((start, end))
        else:
            # Merge overlapping
            merged[-1] = (
                merged[-1][0],
                max(merged[-1][1], end)
            )
    
    return merged


def build_highlight(text, matches):
    """Build highlighted text"""
    parts = []
    last = 0

    for start, end in matches:
        parts.append(text[last:start])
        parts.append(click.style(text[start:end], fg='green'))
        last = end
    parts.append(text[last:])

    return ''.join(parts)


def echo(results: dict):
    """Display results with a specific format and color scheme"""
    for match_type, datas in results.items():
        if datas:
            RESULT_TITLES = {
                "file": "Files",
                "directory": "Directories",
                "content": "Contents"
            }
            click.secho(f'\n{RESULT_TITLES[match_type]}\n────────────────', fg='yellow')

            for data in datas:
                if match_type == 'content':  # Print a content-search result and its matching lines
                    separator = click.style("::", fg="yellow")
                    # Print file path
                    click.echo(
                        separator.join(
                            [click.style(data.path, fg="cyan"), *(
                                click.style(path, fg="cyan")
                                for path in data.virtual_path
                            )]
                        )
                    )
                    
                    # Print file lines
                    for line in data.lines:
                        matches = merge_matches(line.matches)
                        # Keep the original count so overlapping matches are still counted separately
                        count = len(line.matches)
                        
                        # Show a note if the pattern repeats 3 or more times
                        count_query = f' ({count} matches)' if count >= 3 else ''
                        
                        prefix = click.style(
                            f"Line {line.number}{count_query}: ",
                            fg="magenta",
                        )
                        output_line = prefix + build_highlight(line.text, matches)

                        click.echo(output_line)
                    
                    # Print a blank line to separate results
                    if data.lines:
                        print()
                else:  # Print a file or directory match, including archive paths
                    matches = merge_matches(data.matches)
                    
                    if data.virtual_path:  # Render archive results
                        separator = click.style("::", fg="yellow")
                        virtual_file_name = build_highlight(
                            data.virtual_path[-1],
                            matches
                        )

                        click.echo(
                            separator.join(
                                [data.path, *data.virtual_path[0:-1], virtual_file_name]
                            )
                        )
                    else:
                        click.echo(
                            build_highlight(data.path, matches)
                        )


def echo_stats(config, results, metrics, elapsed_time=None):
    """Render stats in a specific format and color scheme for display in the terminal"""
    
    INDENT = '  '
    click.secho('\nStatistics\n────────────────', fg='yellow')

    click.secho('Results', fg="cyan")
    if config.file:
        click.echo(INDENT + f'Files matched: {len(results["file"]):,}')
    
    if config.directory:
        click.echo(INDENT + f'Directories matched: {len(results["directory"]):,}')

    if config.content:
        click.echo(INDENT + f'Files with matched content: {len(results["content"]):,}')
        
        lines_matched = sum(len(file.lines) for file in results["content"])
        matches = sum(
            len(line.matches)
            for file in results["content"]
            for line in file.lines
        )
        
        if lines_matched:
            click.echo(INDENT + f"Lines matched: {lines_matched:,}")
        if matches:
            click.echo(INDENT + f"Matches: {matches:,}")
    
    click.secho('\nSearch', fg="cyan")
    if config.file or config.content:
        click.echo(INDENT + f"Files scanned: {len(metrics['files_scanned']):,}")
    if config.archive:
        click.echo(INDENT + f"Archives scanned: {len(metrics['archives_scanned']):,}")
    click.echo(INDENT + f"Directories scanned: {len(metrics['directories_scanned']):,}")
    
    click.echo(click.style("\nSearch time: ", fg='magenta') + f'{elapsed_time:.6f}s')


def search_worker(config, result_queue):
    """Run the search in a separate process so it can be terminated on timeout"""

    try:
        seek(config, result_queue=result_queue)

        # Tell the parent process that the search completed successfully.
        result_queue.put(("done", None))
    except Exception as e:
        # Send the exception to the parent process so it can be raised there.
        result_queue.put(("error", e))


def drain_results(result_queue, results, metrics):
    """Consume all messages currently available in the queue"""
    
    # We use "while True" because we don't know how many messages are inside the Queue.
    # It may be empty or have 3 values in it or 5 values or more
    while True:
        try:
            # get_nowait() prevents the parent process from blocking while waiting for new data.
            # The difference from get() is that if the Queue is empty, get() waits
            # and the timeout check afterward isn't executed, but get_nowait() raises Empty exception
            # if the Queue is empty
            message_type, data = result_queue.get_nowait()
        except Empty:
            # No more messages are currently available.
            break

        if message_type in ('file', 'directory', 'content'):
            results[message_type].append(data)
        elif message_type == 'metric':
            name, value = data
            metrics[name].add(value)
        elif message_type == 'error':
            raise data
        elif message_type == 'done':
            return True

    return False


def search_with_timeout(config):
    """
    Returns:
        dict: Results found during the search
        dict: Metrics for use in stats
        float: The time it took for the search to finish
        bool: Has the search hit time limit or not?
    """

    # Queue is used to safely send results and metrics from the worker
    # process back to the parent process.
    result_queue = Queue()

    results = {
        'file': [],
        'directory': [],
        'content': [],
    }
    metrics = defaultdict(set)

    process = Process(
        target=search_worker,
        args=(config, result_queue),
    )

    start = time.perf_counter()
    process.start()

    while True:
        # Collect everything the worker has produced since the last check.
        finished = drain_results(result_queue, results, metrics)

        if finished:
            # The worker has already finished, so wait for it to exit cleanly.
            process.join()

            elapsed = time.perf_counter() - start
            return results, metrics, elapsed, False

        elapsed = time.perf_counter() - start

        if elapsed >= config.timeout:
            # The search exceeded the allowed time.
            # Wait for OS to kill the process.
            process.terminate()
            process.join()

            # Collect any results that were put into the queue immediately
            # before the worker was terminated.
            drain_results(result_queue, results, metrics)

            return results, metrics, elapsed, True
        
        # Give the worker some time to produce more results before checking again.
        # A short sleep also prevents the parent process from continuously
        # consuming CPU in this loop.
        time.sleep(0.0005)


@click.command()
@click.argument('query')
@click.argument('path', type=click.Path(exists=True, file_okay=False, dir_okay=True),
                default='.', required=False)
# Search type options
@click.option('-f', '--file', is_flag=True, help='Search only in file names.')
@click.option('-d', '--directory', is_flag=True, help='Search only in directory names.')
@click.option('-c', '--content', is_flag=True, help='Search within file contents.')
# Additional options
@click.option('-C', '--case-sensitive', is_flag=True,
              help='Make the search case-sensitive '
                   '(except when --expr is enabled, '
                   'in which case you can make it case sensitive by putting c before term: c"foo")')
@click.option('-r', '--regex', is_flag=True,
              help='Use regular expressions to search '
                   '(except when --expr is enabled, '
                   'in which case you can make it regex by putting r before term: r"foo")')
@click.option('-w', '--word', is_flag=True,
              help='Match whole words only '
                   '(except when --expr is enabled, '
                   'in which case you can make it match whole word by putting w before term: w"foo")')
@click.option('--expr', is_flag=True,
              help='Enable boolean query expressions. Example: r"foo.*bar" and ("bar" or "baz") and not "qux". '
                   'Prefixes: r=regex, c=case-sensitive, w=whole-word, f=fuzzy.')
@click.option('--timeout', type=click.FloatRange(min=0, min_open=True),
              help='Stop the search after the specified number of seconds.')
@click.option('--fuzzy', is_flag=True, help='Enable fuzzy search (approximate matching). '
              'except when --expr is enabled, '
              'in which case you can make it fuzzy by putting f before term: f"foo"')
@click.option('--fuzzy-level', type=click.IntRange(1, 99), default=80, show_default=True,
              help='Fuzzy matching threshold (1-99). Higher values require closer matches.')
# Extension filters
@click.option('--ext', multiple=True, type=click.STRING,
              help='Include files with these extensions. Example: --ext py --ext js')
@click.option('-E', '--exclude-ext', multiple=True, type=click.STRING,
              help='Exclude files with these extensions. Example: --exclude-ext jpg --exclude-ext exe')
# Include/Exclude specific paths (files or directories)
@click.option('-i', '--include', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to include in search.')
@click.option('-e', '--exclude', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to exclude from search.')
@click.option('--re-include', type=click.STRING,
              help='Directories or files to include in search with regex.')
@click.option('--re-exclude', type=click.STRING,
              help='Directories or files to exclude from search with regex.')
# Size filters
@click.option('--max-size', type=click.FLOAT, help='Maximum file/directory size (in MB).')
@click.option('--min-size', type=click.FLOAT, help='Minimum file/directory size (in MB).')
# Archive options
@click.option('--archive', is_flag=True,
              help='Enable search within archive files (e.g. zip, rar, 7z, gz, bz2, xz, tar, tar.gz, tar.bz2, tar.xz)')
@click.option('--depth', type=click.IntRange(min=0), show_default=True,
              help='Maximum nested archive depth. Example: 2 allows searching up to two archive levels.')
@click.option('--arc-ext', multiple=True, type=click.STRING,
              help='Include files with these extensions inside archive files. Example: --arc-ext py --arc-ext js')
@click.option('--arc-exc-ext', multiple=True, type=click.STRING,
              help='Exclude files with these extensions inside archive files. Example: --arc-exc-ext jpg --arc-exc-ext exe')
@click.option('--arc-include', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to include in search for inside archive files.')
@click.option('--arc-exclude', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to exclude from search for inside archive files.')
@click.option('--arc-max', type=click.FLOAT, help='Maximum size of files in the archive (in MB).')
@click.option('--arc-min', type=click.FLOAT, help='Minimum size of files in the archive (in MB).')
@click.option('--rar-backend', type=click.Path(exists=True, file_okay=True, dir_okay=False),
              help='Path to RAR backend tool (e.g. UnRAR.exe, ...). '
                   'Enter the file type in the query (e.g. unrar, bsdtar, unar, 7z).')
# Output option
@click.option('-a', '--absolute-path', is_flag=True, help='Display full paths for results.')
@click.option('--paths-only', is_flag=True, help='Only show matching file paths for content search.')
@click.option('-s', '--stats', is_flag=True,
              help='Show search statistics including result counts and search time.')
def search(**kwargs):
    """Search for files, directories, and file content based on the query."""

    config = SearchConfig(**kwargs)

    check_rar_backend(config.archive, config.rar_backend, config.query)

    if not config.expr and config.fuzzy:
        if not config.word:
            click.secho(
                "Warning: Fuzzy substring highlighting and counting matches are disabled to improve performance.",
                fg="yellow"
            )
        elif config.word and " " in config.query:
            click.secho(
                'Warning: When using "--fuzzy" and "--word", it is better to have the query be a word and '
                'not a phrase, as this will cause errors in the results.',
                fg="yellow"
            )

    # If no search type is specified, search in all types.
    if not any((config.file, config.directory, config.content)):
        config.file = config.directory = config.content = True

    if config.timeout:
        results, metrics, elapsed, timed_out = search_with_timeout(config)

        # Even if the search timed out, display all results found before termination.
        echo(results)

        if timed_out:
            click.secho(
                f"\nTimeout! Search exceeded {config.timeout} seconds.",
                fg="red",
            )

        if config.stats:
            echo_stats(config, results, metrics, elapsed)
    else:
        start = time.perf_counter()
        results, metrics = seek(config)
        elapsed = time.perf_counter() - start
        
        echo(results)
        if config.stats:
            echo_stats(config, results, metrics, elapsed)


if __name__ == "__main__":
    search()
