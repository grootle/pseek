import mmap, os
from errno import ELOOP
from pseek import _pignore
from pathlib import Path
from collections import defaultdict, deque
from .utils import get_path_suffix, is_binary
from .parser import parse_query_expression, TermNode, find_matches
from .archive import ARCHIVE_EXTS, extract_names_from_archive, extract_text_from_archive
from .structs import FileDirResult, ContentResult, MatchGroup, Line


def should_skip(config, p: Path, file_ext: str, p_size: int) -> bool:
    """
    Check whether the file/directory should be skipped based on various filters.
    Returns True if the path should be skipped.
    """
    if (config.ext and file_ext not in config.ext) \
        or (config.exclude_ext and file_ext in config.exclude_ext) \
        or (config.size and (p.is_dir() or not any(  # .stat().st_size doesn't give actual size of dir.
                                                     # To measure the actual size,
                                                     # total size of all files inside it must be calculated,
                                                     # which is time-consuming
            minimum <= p_size <= maximum
            for minimum, maximum in config.size
        ))):
        return True

    # Filter by regex include and exclude
    str_p = str(p)
    if config.re_include:
        return not config.re_include.search(str_p)
    if config.re_exclude:
        return config.re_exclude.search(str_p) is not None

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


def search_file_and_dir(config, matches: dict, pattern, p: Path,
                        p_ext: str, metrics, result_queue):
    """Search files and folders on the system and within archive files"""

    path_str = str(p)
    # Filter by requested path type first to avoid unnecessary pattern matching
    match_type = (
        'file' if config.file and p.is_file() else
        'directory' if config.directory and p.is_dir() else
        None
    )

    if match_type and pattern.evaluate(p.name):
        # Find matched query in the name
        name_matches = find_matches(
            pattern,
            p.name,
            # Calculate number of chars that come before name of file or dir
            len(path_str) - len(p.name)
        )

        add_result(
            matches,
            result_queue,
            match_type,
            FileDirResult(
                path=path_str,
                matches=name_matches
            )
        )

    # Search for files and directories name inside archive files if archive is active
    if config.archive and p_ext in ARCHIVE_EXTS[:-3]:
        for virtual_path, name, is_dir in extract_names_from_archive(p, config):
            if config.stats:
                full_virtual_path = (path_str, *virtual_path, str(name))
                
                if not is_dir and config.file:
                    add_metric(metrics, result_queue, 'files_scanned', full_virtual_path)
                elif is_dir:
                    add_metric(metrics, result_queue, 'directories_scanned', full_virtual_path)
                
                # We cannot use "full_virtual_path[-1]" because it may be limited by --arc-depth
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
                        path=path_str,
                        matches=name_matches,
                        virtual_path=[*virtual_path, str(name)]
                    )
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


def search_content(config, matches: dict, pattern, binary_pattern,
                   p: Path, p_ext: str, metrics, result_queue):
    """Search within the contents of system files and files inside archive files"""

    path_str = str(p)

    # Search files content inside archives separately.
    if config.archive and p_ext in ARCHIVE_EXTS:
        for virtual_path, content in extract_text_from_archive(p, config):
            if config.stats:
                full_virtual_path = (path_str, *virtual_path)

                add_metric(
                    metrics,
                    result_queue,
                    'files_scanned',
                    full_virtual_path if virtual_path else path_str
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

            collector = ContextCollector(config.context)
            for num, line in enumerate(decoded_content.splitlines(), 1):
                matched = pattern.evaluate(line)

                if config.paths_only and matched:
                    add_result(
                        matches,
                        result_queue,
                        'content',
                        ContentResult(
                            path=path_str,
                            virtual_path=virtual_path
                        )
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
                        path=path_str,
                        virtual_path=virtual_path,
                        groups=groups
                    )
                )

        # Skip next block to avoid searching the contents of archive files
        return

    collector = ContextCollector(config.context)
    # Memory-map the file for efficient access
    with open(p, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        head = mm[:8192]
        if is_binary(head) or (binary_pattern and not content_contains(mm, binary_pattern)):
            return

        mm.seek(0)  # Move the cursor to the beginning of the file

        # Iterate over each line in the file
        for num, line in enumerate(iter(mm.readline, b''), 1):
            try:
                line_decoded = line.decode('utf-8').rstrip('\r\n')
            except UnicodeDecodeError:
                # Skip lines that can't be decoded
                continue

            matched = pattern.evaluate(line_decoded)

            # Avoid searching through the entire file content if the paths-only flag is True
            if config.paths_only and matched:
                add_result(
                    matches,
                    result_queue,
                    'content',
                    ContentResult(path=path_str)
                )
                return

            line_instance = Line(num, line_decoded)

            if matched:
                line_instance.matches = find_matches(pattern, line_decoded)

            collector.process(line_instance, matched)

    groups = collector.finish()
    if groups:
        add_result(
            matches,
            result_queue,
            'content',
            ContentResult(
                path=path_str,
                groups=groups
            )
        )


def is_symlink_valid(entry):
    if not entry.is_symlink():
        return True

    try:
        entry.stat(follow_symlinks=True)
    except (OSError, FileNotFoundError):
        # To skip symlink loops and broken links
        return False

    return True


def walk_logic(path: Path, config, depth: int, matcher, ancestors: set):
    """Recursively walk a directory while pruning excluded subtrees"""

    dir_key = os.path.normcase(os.path.realpath(path))
    if dir_key in ancestors:
        # Prevent recursion through a directory symlink loop
        return
    ancestors.add(dir_key)

    new_depth = depth + 1

    try:
        with os.scandir(path) as entries:
            for entry in entries:
                entry_path = Path(entry.path)

                # Prune explicitly excluded paths before further processing
                if entry_path in config.exclude:
                    continue

                try:
                    is_dir = entry.is_dir(follow_symlinks=config.follow)
                except OSError as e:
                    # If symbolic link loop is encountered,
                    # don't continue to yield entry_path
                    if e.errno != ELOOP:
                        continue
                    is_dir = False

                # Ignore rules / hidden filtering / glob logic
                absolute_entry = (
                    Path(os.path.abspath(entry_path))
                    if not config.absolute_path else entry_path
                ).as_posix()
                ignored, whitelisted, should_descend = (
                    matcher.match_path(
                        absolute_entry,
                        # We don't need target of symlink; symlink itself is always a file
                        is_dir if not entry.is_symlink() else False
                    )
                )

                if ignored:
                    continue

                if any(mi <= new_depth <= ma for mi, ma in config.depth):
                    # A directory with no matching positive glob may still need
                    # to be traversed, but should not necessarily be displayed.
                    # This flag is used in seek func to indicate that this dir
                    # doesn't need to be displayed, even though it must still
                    # be included in metric calculation.
                    metric_only = is_dir and matcher.has_positive_globs and not whitelisted

                    # A symlink may be a valid filename-search candidate even
                    # when its target is not followed or cannot be resolved.
                    yield entry_path, metric_only

                    if config.follow and entry.is_symlink() and is_symlink_valid(entry):
                        yield entry_path.resolve(), False

                if is_dir and should_descend and is_symlink_valid(entry) and \
                    any(new_depth < d[1] for d in config.depth):
                    yield from walk_logic(
                        entry_path,
                        config,
                        new_depth,
                        matcher,
                        ancestors
                    )
    except (OSError, FileNotFoundError):
        pass
    finally:
        ancestors.remove(dir_key)


def walk(config):
    """Include paths define traversal roots, avoiding unnecessary traversal 
    of unrelated parts of the tree"""
    roots = config.include or {config.path}

    for root in roots:
        depth = len(root.relative_to(config.path).parts) - 1

        if any(mi <= depth <= ma for mi, ma in config.depth):
            # Yield symlink path and its target path if requested
            yield root, False
            if config.follow and root.is_symlink() and is_symlink_valid(root):
                yield root.resolve(), False

        if root.is_dir() and any(depth < d[1] for d in config.depth):
            matcher = _pignore.IgnoreMatcher(
                Path(os.path.abspath(root)).as_posix(),
                git_ignore=not config.no_git_ignore,
                ignore=not config.no_ignore_dot,
                git_exclude=not config.no_ignore_exclude,
                git_global=not config.no_ignore_global,
                parents=not config.no_ignore_parent,
                require_git=not config.no_require_git,
                hidden=not config.hidden,
                globs=list(config.glob) or None,
                glob_root=config.path.as_posix()
            )

            yield from walk_logic(root, config, depth, matcher, set())


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

    for p, metric_only in walk(config):
        # Dir metrics must be added before should_skip,
        # as it can influence these metrics
        if config.stats and p.is_dir():
            add_metric(metrics, result_queue, 'directories_scanned', str(p))

        if metric_only:
            continue

        try:
            p_ext = get_path_suffix(p)
            # Path.state follows symlinks, so we use lstate here
            p_size = p.lstat().st_size
        except OSError:
            continue

        if should_skip(config, p, p_ext, p_size):
            continue

        if config.stats:
            path_str = str(p)

            if (config.file or config.content) and p.is_file():
                add_metric(metrics, result_queue, 'files_scanned', path_str)

            if config.archive and p_ext in ARCHIVE_EXTS:
                add_metric(
                    metrics,
                    result_queue,
                    'archives_scanned',
                    (path_str,)
                )

        # Search for files and directories if requested
        if config.file or config.directory:
            search_file_and_dir(config, matches, pattern, p,
                                p_ext, metrics, result_queue)
        
        # Search for content inside files if requested
        # Avoid empty files
        if config.content and not p.is_symlink() \
            and p.is_file() and p_size != 0:
            search_content(config, matches, pattern, binary_pattern, p,
                           p_ext, metrics, result_queue)

    return matches, metrics
