import os
import re
import unicodedata
from pathlib import Path

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

    # Preserve deterministic ordering for equal natural keys.
    original_path = (
        getattr(data.path, 'string', data.path),
        *(
            getattr(path, 'string', path)
            for path in data.virtual_path
        )
    )

    return natural_key, original_path


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
        return (key is None, key)


def sort_results(sortby: str, datas: list, match_type: str):
    match sortby:
        case 'path':
            datas.sort(key=path_sort_key)
        case 'size':
            if match_type != 'directory':
                datas.sort(key=lambda d: (
                    d.virtual_path[-1].size
                    if d.virtual_path else d.path.size
                ))
        case 'modified':
            datas.sort(key=modified_sort_key)
        case 'depth':
            datas.sort(key=depth_sort_key)
        case 'accessed':
            datas.sort(key=accessed_sort_key)
        case 'matches':
            if match_type == 'content':
                datas.sort(key=lambda d: sum(
                    len(line.matches)
                    for group in d.groups
                    for line in group.lines
                ))
        case 'natpath':
            datas.sort(key=natpath_sort_key)
        case _:
            pass
