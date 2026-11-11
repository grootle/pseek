import mmap
from collections import deque

from ...structs import ContentResult, FileDirResult, Line, MatchGroup
from ...utils import add_metric, add_result, get_path_suffix, is_binary
from ..archive import (
    ARCHIVE_EXTS,
    extract_names_from_archive,
    extract_text_from_archive,
)
from ..parser import find_matches


def search_paths_inside_archive(
    p,
    config,
    pattern,
    metrics,
    result_queue,
    result_lock,
    matches
):
    for virtual_path, name in extract_names_from_archive(p, config):
        if config.stats:
            full_virtual_path = (p.string, *virtual_path, name.string)
            
            if not name.is_dir and config.file:
                add_metric(
                    metrics,
                    result_queue,
                    'files_scanned',
                    full_virtual_path,
                    result_lock
                )
            elif name.is_dir:
                add_metric(
                    metrics,
                    result_queue,
                    'directories_scanned',
                    full_virtual_path,
                    result_lock
                )
            
            # We cannot use "full_virtual_path[-1]" because it may be limited by --arc-depth
            # and may not enter the archive at all to scan inside it
            if len(full_virtual_path) >= 3 and get_path_suffix(full_virtual_path[-2]) in ARCHIVE_EXTS[:-3]:
                add_metric(
                    metrics,
                    result_queue,
                    'archives_scanned',
                    full_virtual_path,
                    result_lock
                )

        arc_match_type = (
            'file' if config.file and not name.is_dir else
            'directory' if config.directory and name.is_dir else
            None
        )

        if arc_match_type and (pattern is None or pattern.evaluate(name.path)):
            name_matches = find_matches(
                pattern,
                name.path,
                len(name.string)
            )

            add_result(
                matches,
                result_queue,
                arc_match_type,
                FileDirResult(
                    path=p.string,
                    matches=name_matches,
                    virtual_path=[*virtual_path, name.string]
                ),
                result_lock
            )


def search_file_and_dir(config, matches: dict, pattern, p,
                        metrics, result_queue, result_lock):
    """Search files and folders on the system and within archive files"""

    # Filter by requested path type first to avoid unnecessary pattern matching
    match_type = (
        'file' if config.file and p.is_file else
        'directory' if config.directory and p.is_dir else
        None
    )

    if match_type and (pattern is None or pattern.evaluate(p.path)):
        # Find matched query in the name
        name_matches = find_matches(
            pattern,
            p.path,
            len(p.string)
        )

        add_result(
            matches,
            result_queue,
            match_type,
            FileDirResult(
                path=p.string,
                matches=name_matches
            ),
            result_lock
        )

    # Search for files and directories name inside archive files if archive is active
    if config.archive and p.suffix in ARCHIVE_EXTS[:-3]:
        search_paths_inside_archive(
            p,
            config,
            pattern,
            metrics,
            result_queue,
            result_lock,
            matches
        )


def content_contains(content, binary_pattern) -> bool:
    """
    Fast pre-check for presence of query in file.
    If query isn't present, file can be skipped.
    """
    if isinstance(content, mmap.mmap):
        return content.find(binary_pattern) != -1
    return binary_pattern in content


class ContextCollector:
    """
    Collects matching lines and their surrounding context into
    non-overlapping MatchGroups in a single pass.
    """

    def __init__(self, context: tuple[int, int]):
        # Lines immediately preceding the current search position
        self.before_buffer = deque(maxlen=context[0])
        # Lines after the latest match, kept until the group is finalized
        # or another match extends the same group
        self.after_buffer = []
        self.before = context[0]
        self.after = context[1]
        self.lines = []
        self.matching_lines = set()
        self.groups = []

    def _finish_group(self):
        self.lines.extend(self.after_buffer[:self.after])
        self.groups.append(
            MatchGroup(
                self.lines,
                self.matching_lines
            )
        )

        self.before_buffer.clear()
        # Preserve the latest lines as before-context for the next group.
        self.before_buffer.extend(self.after_buffer)
        self.after_buffer.clear()
        # Because of ownership, we can't use .clear() here.
        # Using it could also clear values inside MatchGroup.
        self.lines = []
        self.matching_lines = set()

    def process(self, line: Line, matched: bool):
        if matched:
            if self.matching_lines:
                self.lines.extend(self.after_buffer)
                self.lines.append(line)

                self.after_buffer.clear()
            else:
                self.lines.extend(self.before_buffer)
                self.lines.append(line)

            self.matching_lines.add(line.number)
        else:
            if self.matching_lines:
                self.after_buffer.append(line)

                # Keep groups together while their context ranges overlap or touch
                if len(self.after_buffer) > self.after + self.before:
                    self._finish_group()
            else:
                self.before_buffer.append(line)

    def finish(self) -> list[MatchGroup]:
        if self.matching_lines:
            self._finish_group()

        return self.groups


def search_archive_content(
    p,
    config,
    pattern,
    binary_pattern,
    metrics,
    result_queue,
    result_lock,
    matches
):
    for virtual_path, content in extract_text_from_archive(p, config):
        if config.stats:
            full_virtual_path = (p.string, *virtual_path)

            add_metric(
                metrics,
                result_queue,
                'files_scanned',
                full_virtual_path if virtual_path else p.string,
                result_lock
            )

            if (len(full_virtual_path) >= 3 and get_path_suffix(full_virtual_path[-2]) in ARCHIVE_EXTS[:-3] \
                or get_path_suffix(full_virtual_path[-1]) in ARCHIVE_EXTS[-3:]):
                add_metric(
                    metrics,
                    result_queue,
                    'archives_scanned',
                    full_virtual_path,
                    result_lock
                )

        if binary_pattern and not content_contains(content, binary_pattern):
            continue
        
        # Try decoding byte data to UTF-8 text. Continue if decoding fails
        try:
            decoded_content = content.decode('utf-8')
        except UnicodeDecodeError:
            continue

        collector = ContextCollector(config.context)
        for num, line in enumerate(decoded_content.splitlines(), 1):
            matched = pattern is None or pattern.evaluate(line)

            if config.paths_only and matched:
                add_result(
                    matches,
                    result_queue,
                    'content',
                    ContentResult(
                        path=p.string,
                        virtual_path=virtual_path
                    ),
                    result_lock
                )
                break

            line_instance = Line(num, line)

            if matched:
                line_instance.matches = find_matches(pattern, line)

            collector.process(line_instance, matched)

        groups = collector.finish()
        if groups:
            add_result(
                matches,
                result_queue,
                'content',
                ContentResult(
                    path=p.string,
                    virtual_path=virtual_path,
                    groups=groups
                ),
                result_lock
            )


def search_content(config, matches: dict, pattern, binary_pattern,
                   p, metrics, result_queue, result_lock):
    """Search within the contents of system files and files inside archive files"""

    # Search files content inside archives separately.
    if config.archive and p.suffix in ARCHIVE_EXTS:
        search_archive_content(
            p,
            config,
            pattern,
            binary_pattern,
            metrics,
            result_queue,
            result_lock,
            matches
        )

        # Skip next block to avoid searching the contents of archive files
        return

    collector = ContextCollector(config.context)
    try:
        # Memory-map the file for efficient access
        with open(p.path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            head = mm[:8192]
            if is_binary(head) or (binary_pattern and not content_contains(mm, binary_pattern)):
                return

            mm.seek(0)  # Move the cursor to the beginning of the file

            # Iterate over each line in the file
            for num, line in enumerate(iter(mm.readline, b''), 1):
                if binary_pattern and not content_contains(line, binary_pattern):
                    continue

                try:
                    line_decoded = line.decode('utf-8').rstrip('\r\n')
                except UnicodeDecodeError:
                    # Skip lines that can't be decoded
                    continue

                matched = pattern is None or pattern.evaluate(line_decoded)

                # Avoid searching through the entire file content if the paths-only flag is True
                if config.paths_only and matched:
                    add_result(
                        matches,
                        result_queue,
                        'content',
                        ContentResult(path=p.string),
                        result_lock
                    )
                    return

                if not any(config.context) and not matched:
                    continue

                line_instance = Line(num, line_decoded)

                if matched:
                    line_instance.matches = find_matches(pattern, line_decoded)

                collector.process(line_instance, matched)
    except OSError:
        return

    groups = collector.finish()
    if groups:
        add_result(
            matches,
            result_queue,
            'content',
            ContentResult(
                path=p.string,
                groups=groups
            ),
            result_lock
        )
