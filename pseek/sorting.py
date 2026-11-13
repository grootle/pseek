import os
import re
import unicodedata
from pathlib import Path

from click import BadParameter

_DIGIT_PATTERN = re.compile(r'(\d+)')


def natural_component_key(value: str) -> tuple:
    """
    Create a natural sort key for a single path component.

    Features:
        - Integer recognition
        - Leading-zero handling
        - Unicode normalization
        - Case-insensitive comparison
    """

    # Normalize Unicode and ignore case.
    value = unicodedata.normalize('NFD', value.casefold())

    parts = []

    for part in _DIGIT_PATTERN.split(value):
        if not part:
            continue

        if part.isdecimal():
            # Convert Unicode decimal digits to ASCII.
            # Returns decimal digit of different alphabets as int.
            # e.g. ۵ -> 5
            digits = ''.join(
                str(unicodedata.decimal(char))
                for char in part
            )

            # Remove leading zeros while preserving zero itself.
            significant = digits.lstrip('0') or '0'

            parts.append((
                1,
                len(significant),
                significant,
                len(part)
            ))
        else:
            parts.append((0, part))

    return tuple(parts)


def path_key(path: Path) -> tuple:
    """ Split and naturally sort path components """

    return tuple(
        natural_component_key(part)
        for part in path.parts
    )


def natpath_sort_key(data) -> tuple:
    """ Create a natural sort key for filesystem and nested archive paths """

    # Keep filesystem and archive path levels separate.
    natural_key = (
        path_key(
            getattr(data.path, 'path', None) or Path(data.path)
        ),
        *(
            # Virtual paths may contain strings and SysPath objects.
            path_key(
                getattr(path, 'path', None) or Path(path)
            )
            for path in data.virtual_path
        )
    )

    return natural_key


def path_sort_key(data) -> tuple:
    original_path = (
        getattr(data.path, 'string', data.path),
        *(
            getattr(path, 'string', path)
            for path in data.virtual_path
        )
    )

    # Normalize case according to the current platform.
    normalized_path = tuple(
        os.path.normcase(part)
        for part in original_path
    )

    # Use the original path to break ties.
    return normalized_path, original_path


def modified_sort_key(data) -> tuple:
    if data.virtual_path:
        key = data.virtual_path[-1].modified
    else:
        key = data.path.modified

    # False = 0, True = 1
    # None values ​​are placed at the end.
    return (key is None, key)


def accessed_sort_key(data) -> tuple:
    if data.virtual_path:
        key = data.virtual_path[-1].accessed
    else:
        key = data.path.accessed

    # False = 0, True = 1
    # None values ​​are placed at the end.
    return (key is None, key)


def depth_sort_key(data) -> tuple:
    if data.virtual_path:
        key = data.virtual_path[-1].depth
        return (key[0] is None, *key)
    else:
        key = data.path.depth
        return (key is None, key, -1)


def size_sort_key(data) -> int:
    return (
        data.virtual_path[-1].size
        if data.virtual_path
        else data.path.size
    )


def matches_sort_key(data) -> int:
    return sum(
        len(line.matches)
        for group in data.groups
        for line in group.lines
    )


SORT_KEYS = {
    'path': path_sort_key,
    'size': size_sort_key,
    'modified': modified_sort_key,
    'accessed': accessed_sort_key,
    'depth': depth_sort_key,
    'matches': matches_sort_key,
    'natpath': natpath_sort_key,
}


def sort_results(sortby: tuple, datas: list, match_type: str):
    if set(sortby) == {'none'}:
        return

    if 'none' in sortby:
        raise BadParameter(
            "'none' cannot be combined with other sort options",
            param_hint='--sort',
        )

    key_functions = []

    # Use dict.fromkeys() to preserve order.
    for name in dict.fromkeys(sortby):
        # Size is not applicable to directories.
        if name == 'size' and match_type == 'directory':
            continue

        # Match count is only applicable to content results.
        if name == 'matches' and match_type != 'content':
            continue

        key_functions.append(SORT_KEYS[name])

    if not key_functions:
        return

    datas.sort(
        key=lambda data: tuple(
            key(data) for key in key_functions
        )
    )
