import mmap, os
from click import style
from pathlib import Path
from .utils import get_path_suffix, EXCLUDED_EXTENSIONS
from .parser import parse_query_expression, TermNode, find_matches
from .archive import ARCHIVE_EXTS, extract_names_from_archive, extract_text_from_archive
from .structs import FileDirResult, ContentResult, LineMatch


def should_skip(config, p_resolved: Path, file_ext: str) -> bool:
    """
    Check whether the file/directory should be skipped based on various filters.
    Returns True if the path should be skipped.
    """
    try:
        p_size_mb = p_resolved.stat().st_size / 1_048_576  # Convert size to MB
    except OSError:
        # If path is inaccessible, skip it.
        return True

    if (config.include and not any(p_resolved.is_relative_to(inc) for inc in config.include)) \
            or (config.exclude and any(p_resolved.is_relative_to(exc) for exc in config.exclude)) \
            or (config.ext and file_ext not in config.ext) \
            or (config.exclude_ext and file_ext in config.exclude_ext) \
            or (config.max_size and p_size_mb > config.max_size) \
            or (config.min_size and p_size_mb < config.min_size):
        return True

    # Filter by regex include and exclude
    if config.re_include:
        return not config.re_include.search(str(p_resolved))
    if config.re_exclude:
        return config.re_exclude.search(str(p_resolved)) is not None

    return False


def search_file_and_dir(config, matches: dict, pattern, p: Path, p_resolved: Path, p_ext: str):
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
        matches[match_type].append(
            FileDirResult(
                path=final_path,
                matches=name_matches
            )
        )

    # Search for files and directories name inside archive files if archive is active
    if config.archive and p_ext in ARCHIVE_EXTS[:-3]:
        for virtual_path, name, is_dir in extract_names_from_archive(p_resolved, config):
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
                matches[arc_match_type].append(
                    FileDirResult(
                        path=final_path,
                        matches=name_matches,
                        virtual_path=[*virtual_path, str(name)]
                    )
                )


def search_content(config, matches: dict, pattern, binary_pattern,
                   p: Path, p_resolved: Path, p_ext: str):
    """Search within the contents of system files and files inside archive files"""
    
    # Avoid empty files for mmap
    if p_resolved.stat().st_size == 0:
        return

    # Choose the file path format based on the absolute_path setting
    file_label = str(p_resolved) if config.absolute_path else str(p)

    # First, check if the file is an archive, extract it from the archive and perform a search
    if config.archive and p_ext in ARCHIVE_EXTS:
        for virtual_path, content in extract_text_from_archive(p, config):
            if binary_pattern and not binary_pattern.search(content):
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
                    matches['content'].append(
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
                matches['content'].append(
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
        if binary_pattern and not binary_pattern.search(mm):
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
                    matches['content'].append(
                        ContentResult(path=file_label)
                    )
                    break
                line_matches = find_matches(pattern, line_decoded)
                lines.append(
                    LineMatch(num, line_decoded, line_matches)
                )

    if lines:
        matches['content'].append(
            ContentResult(
                path=file_label,
                lines=lines
            )
        )


def seek(config) -> dict:
    """Main search function"""
    pattern = parse_query_expression(config)
    # If expression is simple and is a single TermNode, we can use binary pattern
    if config.content:
        binary_pattern = None
        if isinstance(pattern, TermNode):
            try:
                binary_pattern = pattern.get_binary_pattern()
            except Exception:
                pass

    matches = {'file': [], 'directory': [], 'content': []}

    for p in config.path.rglob('*'):
        try:
            p_resolved = p.resolve()
            p_ext = get_path_suffix(p_resolved)
        except OSError:
            continue
        # Skip if conditions fail
        if should_skip(config, p_resolved, p_ext):
            continue
        
        # Search for files and directories if requested
        if config.file or config.directory:
            search_file_and_dir(config, matches, pattern, p, p_resolved, p_ext)
        
        # Search for content inside files if requested
        if config.content and p_resolved.is_file() and p_ext not in EXCLUDED_EXTENSIONS:
            search_content(config, matches, pattern, binary_pattern, p, p_resolved, p_ext)

    return matches
