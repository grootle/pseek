import mmap, os
from pathlib import Path
from collections import defaultdict
from .utils import get_path_suffix, is_binary
from .parser import parse_query_expression, TermNode, find_matches
from .archive import ARCHIVE_EXTS, extract_names_from_archive, extract_text_from_archive
from .structs import FileDirResult, ContentResult, LineMatch


def should_skip(config, p_resolved: Path, file_ext: str, p_size: int) -> bool:
    """
    Check whether the file/directory should be skipped based on various filters.
    Returns True if the path should be skipped.
    """
    if (config.ext and file_ext not in config.ext) \
        or (config.exclude_ext and file_ext in config.exclude_ext) \
        or (config.size and (p_resolved.is_dir() or not any(  # .stat().st_size doesn't give actual size of dir.
                                                              # To measure the actual size,
                                                              # total size of all files inside it must be calculated,
                                                              # which is time-consuming
            minimum <= p_size <= maximum
            for minimum, maximum in config.size
        ))):
        return True

    # Filter by regex include and exclude
    if config.re_include:
        return not config.re_include.search(str(p_resolved))
    if config.re_exclude:
        return config.re_exclude.search(str(p_resolved)) is not None

    return False


def add_result(matches, result_queue, match_type, value):
    if result_queue:
        result_queue.put((match_type, value))
    else:
        matches[match_type].append(value)


def add_metric(metrics, result_queue, name, value):
    if result_queue:
        result_queue.put(('metric', (name, value)))
    else:
        metrics[name].add(value)


def search_file_and_dir(config, matches: dict, pattern, p: Path, p_resolved: Path,
                        p_ext: str, metrics, result_queue):
    """Search files and folders on the system and within archive files"""

    # Choose path based on absolute_path flag
    final_path = str(p_resolved) if config.absolute_path else str(p)
    # Filter by requested path type first to avoid unnecessary pattern matching
    match_type = (
        'file' if config.file and p_resolved.is_file() else
        'directory' if config.directory and p_resolved.is_dir() else
        None
    )

    if match_type and pattern.evaluate(p.name):
        # Find matched query in the name
        name_matches = find_matches(
            pattern,
            p.name,
            # Calculate number of chars that come before name of file or dir
            len(final_path) - len(p.name)
        )

        add_result(
            matches,
            result_queue,
            match_type,
            FileDirResult(
                path=final_path,
                matches=name_matches
            )
        )

    # Search for files and directories name inside archive files if archive is active
    if config.archive and p_ext in ARCHIVE_EXTS[:-3]:
        for virtual_path, name, is_dir in extract_names_from_archive(p_resolved, config):
            if config.stats:
                full_virtual_path = (str(p_resolved), *virtual_path, str(name))
                
                if not is_dir and config.file:
                    add_metric(metrics, result_queue, 'files_scanned', full_virtual_path)
                elif is_dir:
                    add_metric(metrics, result_queue, 'directories_scanned', full_virtual_path)
                
                # We cannot use "full_virtual_path[-1]" because it may be limited by --depth
                # and may not enter the archive at all to scan inside it
                if len(full_virtual_path) >= 3 and get_path_suffix(full_virtual_path[-2]) in ARCHIVE_EXTS[:-3]:
                    add_metric(metrics, result_queue, 'archives_scanned', full_virtual_path)

            arc_match_type = (
                'file' if config.file and not is_dir else
                'directory' if config.directory and is_dir else
                None
            )
            
            if arc_match_type and pattern.evaluate(name.name):
                name_matches = find_matches(
                    pattern,
                    name.name,
                    # Calculate number of chars that come before name of file or dir
                    len(str(name)) - len(name.name)
                )

                add_result(
                    matches,
                    result_queue,
                    arc_match_type,
                    FileDirResult(
                        path=final_path,
                        matches=name_matches,
                        virtual_path=[*virtual_path, str(name)]
                    )
                )


def content_contains(content, binary_pattern) -> bool:
    """Fast pre-check for presence of query in file. If query isn't present, file can be skipped"""
    if isinstance(binary_pattern, bytes):
        if isinstance(content, mmap.mmap):
            return content.find(binary_pattern) != -1
        return binary_pattern in content

    return binary_pattern.search(content) is not None


def search_content(config, matches: dict, pattern, binary_pattern,
                   p: Path, p_resolved: Path, p_ext: str, metrics, result_queue):
    """Search within the contents of system files and files inside archive files"""

    # Choose the file path format based on the absolute_path setting
    file_label = str(p_resolved) if config.absolute_path else str(p)

    # First, check if the file is an archive, extract it from the archive and perform a search
    if config.archive and p_ext in ARCHIVE_EXTS:
        for virtual_path, content in extract_text_from_archive(p, config):
            if config.stats:
                full_virtual_path = (str(p_resolved), *virtual_path)

                add_metric(
                    metrics,
                    result_queue,
                    'files_scanned',
                    full_virtual_path if virtual_path else str(p_resolved)
                )

                if (len(full_virtual_path) >= 3 and get_path_suffix(full_virtual_path[-2]) in ARCHIVE_EXTS[:-3] \
                    or get_path_suffix(full_virtual_path[-1]) in ARCHIVE_EXTS[-3:]):
                    add_metric(metrics, result_queue, 'archives_scanned', full_virtual_path)

            if binary_pattern and not content_contains(content, binary_pattern):
                continue
            
            # Try decoding byte data to UTF-8 text. Continue if decoding fails
            try:
                decoded_content = content.decode('utf-8')
            except UnicodeDecodeError:
                continue

            lines = []
            for num, line in enumerate(decoded_content.splitlines(), 1):
                if not pattern.evaluate(line):
                    continue

                if config.paths_only:
                    add_result(
                        matches,
                        result_queue,
                        'content',
                        ContentResult(
                            path=file_label,
                            virtual_path=virtual_path
                        )
                    )

                    break

                line_matches = find_matches(pattern, line.strip())
                lines.append(
                    LineMatch(num, line.strip(), line_matches)
                )

            if lines:
                add_result(
                    matches,
                    result_queue,
                    'content',
                    ContentResult(
                        path=file_label,
                        virtual_path=virtual_path,
                        lines=lines
                    )
                )

        # Skip next block to avoid searching the contents of archive files
        return

    lines = []
    # Memory-map the file for efficient access
    with open(p, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        head = mm[:8192]
        if is_binary(head) or (binary_pattern and not content_contains(mm, binary_pattern)):
            return

        mm.seek(0)  # Move the cursor to the beginning of the file

        # Iterate over each line in the file
        for num, line in enumerate(iter(mm.readline, b''), 1):
            try:
                # Decode the binary line as UTF-8 and strip whitespace
                line_decoded = line.decode('utf-8').strip()
            except UnicodeDecodeError:
                # Skip lines that can't be decoded
                continue

            # If the pattern matches in the decoded line
            if pattern.evaluate(line_decoded):
                # Avoid searching through the entire file content if the fast-content flag is True
                if config.paths_only:
                    add_result(
                        matches,
                        result_queue,
                        'content',
                        ContentResult(path=file_label)
                    )

                    break
                line_matches = find_matches(pattern, line_decoded)
                lines.append(
                    LineMatch(num, line_decoded, line_matches)
                )

    if lines:
        add_result(
            matches,
            result_queue,
            'content',
            ContentResult(
                path=file_label,
                lines=lines
            )
        )


def walk_logic(path: Path, exclude: set[Path]):
    """Recursively walk a directory while pruning excluded subtrees"""

    with os.scandir(path) as entries:
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                entry_path_resolved = entry_path.resolve()
            except OSError:
                continue
            
            if entry_path_resolved in exclude:
                continue

            if entry.is_dir(follow_symlinks=False):
                yield from walk_logic(entry.path, exclude)
            yield entry_path, entry_path_resolved


def walk(path: Path, include: set[Path], exclude: set[Path]):
    """Include paths define traversal roots, avoiding unnecessary traversal 
    of unrelated parts of the tree"""
    roots = include or {path}

    for root in roots:
        try:
            root_resolved = root.resolve()
        except OSError:
            continue

        if root_resolved in exclude:
            continue

        if root.is_dir():
            yield from walk_logic(root, exclude)
        yield root, root_resolved


def seek(config, result_queue=None) -> dict:
    """Main search function"""
    pattern = parse_query_expression(config)
    # If expression is simple and is a single TermNode, we can use binary pattern
    if config.content:
        if isinstance(pattern, TermNode):
            binary_pattern = pattern.get_binary_pattern()
        else:
            binary_pattern = None

    matches = {'file': [], 'directory': [], 'content': []}
    metrics = defaultdict(set)

    for p, p_resolved in walk(config.path, config.include, config.exclude):
        try:
            p_ext = get_path_suffix(p_resolved)
            p_size = p_resolved.stat().st_size
        except OSError:
            continue
        if should_skip(config, p_resolved, p_ext, p_size):
            continue

        if config.stats:
            str_p_resolved = str(p_resolved)

            if p_resolved.is_file() and (config.file or config.content):
                add_metric(metrics, result_queue, 'files_scanned', str_p_resolved)
            elif p_resolved.is_dir():
                add_metric(metrics, result_queue, 'directories_scanned', str_p_resolved)

            if config.archive and p_ext in ARCHIVE_EXTS:
                add_metric(
                    metrics,
                    result_queue,
                    'archives_scanned',
                    (str_p_resolved,)
                )

        # Search for files and directories if requested
        if config.file or config.directory:
            search_file_and_dir(config, matches, pattern, p, p_resolved,
                                p_ext, metrics, result_queue)
        
        # Search for content inside files if requested
        if config.content and p_resolved.is_file() and p_size != 0:  # Avoid empty files
            search_content(config, matches, pattern, binary_pattern, p, p_resolved,
                           p_ext, metrics, result_queue)

    return matches, metrics
