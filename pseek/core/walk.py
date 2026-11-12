import os
import stat
from errno import ELOOP
from pathlib import Path

import click

from pseek import _pignore

from ..structs import SysPath


def is_symlink_valid(entry, is_symlink):
    if not is_symlink:
        return True

    try:
        entry.stat(follow_symlinks=True)
    except (OSError, FileNotFoundError):
        # To skip symlink loops and broken links
        return False

    return True


def needs_ignore_matcher(config) -> bool:
    # In cases where all paths must be searched and
    # there are no filtering rules,
    # there is no need to create matcher.
    return (
        not config.hidden
        or not config.no_git_ignore
        or not config.no_ignore_dot
        or not config.no_ignore_exclude
        or not config.no_ignore_global
        or bool(config.glob)
    )


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
                # Filter by regex include and exclude
                if (config.re_include and not config.re_include.search(entry_path.name)) \
                    or (config.re_exclude and config.re_exclude.search(entry_path.name) is not None):
                    continue

                try:
                    is_dir = entry.is_dir(follow_symlinks=config.follow)
                except OSError as e:
                    # If symbolic link loop is encountered,
                    # don't continue to yield entry_path
                    if e.errno != ELOOP:
                        continue
                    is_dir = False

                is_symlink = entry.is_symlink()

                if matcher is None:
                    ignored = False
                    whitelisted = False
                    should_descend = is_dir
                else:
                    # Ignore rules / hidden filtering / glob logic

                    absolute_entry = (
                        Path(os.path.abspath(entry_path))
                        if not config.absolute_path
                        else entry_path
                    ).as_posix()

                    try:
                        ignored, whitelisted, should_descend = matcher.match_path(
                            absolute_entry,
                            # We don't need target of symlink;
                            # symlink itself is always considered a file.
                            is_dir if not is_symlink else False,
                        )
                    except RuntimeError:
                        continue

                if ignored:
                    continue

                if any(mi <= new_depth <= ma for mi, ma in config.depth):
                    # A directory with no matching positive glob may still need
                    # to be traversed, but should not necessarily be displayed.
                    # This flag is used in seek func to indicate that this dir
                    # doesn't need to be displayed, even though it must still
                    # be included in metric calculation.
                    metric_only = (
                        is_dir
                        and matcher is not None
                        and matcher.has_positive_globs
                        and not whitelisted
                    )

                    entry_syspath = SysPath(
                        path=entry_path,
                        is_file=entry.is_file(follow_symlinks=False) \
                            if not is_symlink else True,
                        is_dir=is_dir if not is_symlink else False,
                        is_symlink=is_symlink,
                        depth=new_depth
                    )

                    if config.sortby == 'accessed' and entry_syspath.is_dir:
                        try:
                            # Just to save accessed time before scanning dir.
                            # Depending on file system settings,
                            # scanning a dir may change st_atime_ns.
                            entry_syspath.accessed
                        except OSError:
                            continue

                    # A symlink may be a valid filename-search candidate even
                    # when its target is not followed or cannot be resolved.
                    yield (entry_syspath, metric_only)

                    if config.follow and is_symlink and is_symlink_valid(entry, is_symlink):
                        symlink_target = SysPath(
                            # Follow and get the symlink target path
                            path=entry_path.resolve(),
                            is_file=entry.is_file(follow_symlinks=True),
                            is_dir=is_dir,
                            # Target of a symlink isn't a symlink
                            is_symlink=False,
                        )

                        if config.sortby == 'accessed' and symlink_target.is_dir:
                            try:
                                # Just to save accessed time before scanning dir.
                                # Depending on file system settings,
                                # scanning a dir may change st_atime_ns.
                                symlink_target.accessed
                            except OSError:
                                continue

                        yield (symlink_target, False)

                if is_dir and should_descend and is_symlink_valid(entry, is_symlink) and \
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


# TODO: Make traversal parallel just like seek func
def walk(config):
    """Include paths define traversal roots, avoiding unnecessary traversal 
    of unrelated parts of the tree"""
    roots = config.include or {config.path}
    needs_matcher = needs_ignore_matcher(config)

    for root in roots:
        depth = len(root.relative_to(config.path).parts) - 1

        if any(mi <= depth <= ma for mi, ma in config.depth):
            # Yield symlink path and its target path if requested
            is_symlink = root.is_symlink()

            st = root.lstat()

            # Get is_dir and is_file without following the symlink
            is_dir = stat.S_ISDIR(st.st_mode)
            is_file = stat.S_ISREG(st.st_mode)

            root_syspath = SysPath(
                path=root,
                is_file=is_file if not is_symlink else True,
                is_dir=is_dir if not is_symlink else False,
                is_symlink=is_symlink,
                lstat_result=st,
                depth=depth
            )

            if config.sortby == 'accessed' and root_syspath.is_dir:
                try:
                    # Just to save accessed time before scanning dir.
                    # Depending on file system settings,
                    # scanning a dir may change st_atime_ns.
                    root_syspath.accessed
                except OSError:
                    continue

            yield (root_syspath, False)

            if config.follow and is_symlink and is_symlink_valid(root, is_symlink):
                symlink_target = SysPath(
                    path=root.resolve(),
                    # Path.is_file() and Path.is_dir() follow symlinks by default
                    is_file=root.is_file(),
                    is_dir=root.is_dir(),
                    # Target of a symlink isn't a symlink
                    is_symlink=False,
                )

                if config.sortby == 'accessed' and symlink_target.is_dir:
                    try:
                        # Just to save accessed time before scanning dir.
                        # Depending on file system settings,
                        # scanning a dir may change st_atime_ns.
                        symlink_target.accessed
                    except OSError:
                        continue

                yield (symlink_target, False)

        if root.is_dir() and any(depth < d[1] for d in config.depth):
            matcher = None

            if needs_matcher:
                try:
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
                except ValueError as e:
                    raise click.BadParameter(e, param_hint='--glob')
                except RuntimeError as e:
                    click.secho(e, fg='red')
                    raise click.exceptions.Exit(1)

            yield from walk_logic(root, config, depth, matcher, set())
