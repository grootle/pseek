import mmap, os
from click import style
from pathlib import Path
from .utils import get_path_suffix, EXCLUDED_EXTENSIONS
from .parser import parse_query_expression, TermNode, highlight_text
from .archive import ARCHIVE_EXTS, extract_names_from_archive, extract_text_from_archive


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


def seek(config):
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
    # Content: key: file path, value: set of line matches
    matches = {'directory': set(), 'file': set(), 'content': {} if not config.paths_only else set()}

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
            # Choose parent path based on full_path flag
            p_parent = p_resolved.parent if config.full_path else p.parent
            # Filter by requested path type first to avoid unnecessary pattern matching
            match_type = (
                'file' if config.file and p_resolved.is_file() else
                'directory' if config.directory and p_resolved.is_dir() else
                None
            )

            if match_type and pattern.evaluate(p.name):
                # Highlight matched query in the name
                highlighted_name = os.path.join(p_parent, highlight_text(pattern, p.name))
                matches[match_type].add(highlighted_name)

            # Search for files and directories name inside archive files if archive is active
            if config.archive and p_ext in ARCHIVE_EXTS[:-3]:
                for label, name, is_dir in extract_names_from_archive(p_resolved, config):
                    arc_match_type = (
                        'file' if config.file and not is_dir else
                        'directory' if config.directory and is_dir else
                        None
                    )
                    
                    if arc_match_type and pattern.evaluate(name.name):
                        highlighted_name = os.path.join(
                            p_parent,
                            f'{p.name}{label}{name.parent}',
                            highlight_text(pattern, name.name)
                        )
                        matches[arc_match_type].add(highlighted_name)

        # Search for content inside files if requested
        if config.content and p_resolved.is_file() and p_ext not in EXCLUDED_EXTENSIONS:
            try:
                # Avoid empty files for mmap
                if p_resolved.stat().st_size == 0:
                    continue

                # Choose the file path format based on the full_path setting
                file_label = str(p_resolved) if config.full_path else str(p)

                # First, check if the file is an archive, extract it from the archive and perform a search
                if config.archive and p_ext in ARCHIVE_EXTS:
                    for fname, content in extract_text_from_archive(p, config):
                        if binary_pattern and not binary_pattern.search(content):
                            continue
                        
                        # Try decoding byte data to UTF-8 text. Continue if decoding fails
                        try:
                            decoded_content = content.decode('utf-8')
                        except UnicodeDecodeError:
                            continue

                        # Change file_label for archive files
                        archive_label = file_label + fname

                        lines = []
                        for num, line in enumerate(decoded_content.splitlines(), 1):
                            if not pattern.evaluate(line):
                                continue

                            if config.paths_only:
                                matches['content'].add(style(archive_label, fg='cyan'))
                                break

                            count = pattern.count_matches(line) if isinstance(pattern, TermNode) else 0
                            # Highlight the matching parts in green
                            highlighted = highlight_text(pattern, line.strip())
                            # Show a note if the pattern repeats 3 or more times
                            count_query = f' - Repeated {count} times' if count >= 3 else ''
                            # Format the output line with line number and highlighted matches
                            lines.append(
                                style(f'Line {num}{count_query}: ', fg='magenta') + highlighted
                            )

                        if lines:
                            matches['content'][style(archive_label, fg='cyan')] = lines
                    
                    # Skip next block to avoid searching the contents of archive files
                    continue

                lines = []
                # Memory-map the file for efficient access
                with open(p, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    if binary_pattern and not binary_pattern.search(mm):
                        continue

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
                                matches['content'].add(style(file_label, fg='cyan'))
                                break
                            count = pattern.count_matches(line_decoded) if isinstance(pattern, TermNode) else 0
                            # Highlight the matching parts in green
                            highlighted = highlight_text(pattern, line_decoded)
                            # Show a note if the pattern repeats 3 or more times
                            count_query = f' - Repeated {count} times' if count >= 3 else ''
                            # Format the output line with line number and highlighted matches
                            lines.append(
                                style(f'Line {num}{count_query}: ', fg='magenta') + highlighted
                            )

                # If any matching lines were found
                if lines:
                    # Add the file and its matching lines to the results
                    matches['content'][style(file_label, fg='cyan')] = lines
            except Exception:
                continue

    return matches
