from click import BadParameter
import re
from pathlib import Path
from dataclasses import dataclass, field
from math import isfinite
from .utils import compile_regex

SUFFIXES = {
    'b': 1,  # B
    'k': 2 ** 10,  # KiB
    'm': 2 ** 20,  # MiB
    'g': 2 ** 30,  # GiB
    't': 2 ** 40  # TiB
}


def normalize_paths(base_path: Path, paths: tuple[str], param_hint: str):
    result = set()

    for path in paths:
        p = base_path / path
        if not p.exists():
            raise BadParameter(
                f'Path does not exist: {p}',
                param_hint=f'--{param_hint}',
            )
        p = p.resolve() if param_hint == 'exclude' else p

        # Already covered by an existing parent.
        if any(p.is_relative_to(r) for r in result):
            continue

        # Remove existing children covered by this new parent.
        result = {
            r for r in result
            if not r.is_relative_to(p)
        }

        result.add(p)

    return result


def extract_size(size: str, param_hint: str) -> int:
    """Receive size with suffix, perform the validations, and convert it to bytes"""
    
    size_suffix = size[-1:].lower()
    number_str = size[:-1]
    
    if size_suffix not in SUFFIXES:
        raise BadParameter(
            f'Invalid size suffix: {size_suffix}',
            param_hint=f'--{param_hint}',
        )
    
    try:
        number = float(number_str)
    except ValueError:
        raise BadParameter(
            f'Invalid size value: {number_str}',
            param_hint=f'--{param_hint}',
        )
    
    # Avoid receiving values ​​like nan and inf
    if not isfinite(number) or number < 0:
        raise BadParameter(
            f'Invalid size value: {number_str}',
            param_hint=f'--{param_hint}',
        )
    
    # Convert size to B
    return int(number * SUFFIXES[size_suffix])


def compile_sizes(sizes: tuple[str], param_hint: str):
    """Convert sizes list into a list of ranges"""
    
    ranges = []
    
    for size in sizes:
        if size.startswith(':'):
            maximum = extract_size(size[1:], param_hint)
            ranges.append((0, maximum))
        elif size.endswith(':'):
            minimum = extract_size(size[:-1], param_hint)
            ranges.append((minimum, float('inf')))
        elif ':' in size:
            min_str, max_str = size.split(':', 1)
            
            if not min_str or not max_str:
                raise BadParameter(
                    f'Invalid size range: {size}',
                    param_hint=f'--{param_hint}',
                )
            
            minimum = extract_size(min_str, param_hint)
            maximum = extract_size(max_str, param_hint)

            if minimum > maximum:
                raise BadParameter(
                    'Minimum size cannot be greater than maximum size',
                    param_hint=f'--{param_hint}',
                )
            
            ranges.append((minimum, maximum))
        else:
            exact = extract_size(size, param_hint)
            ranges.append((exact, exact))
    
    return ranges


@dataclass
class SearchConfig:
    query: str
    path: Path
    file: bool
    directory: bool
    content: bool
    case_sensitive: bool
    regex: bool
    word: bool
    expr: bool
    timeout: int | None
    fuzzy: bool
    fuzzy_level: int
    ext: set[str]
    exclude_ext: set[str | None]
    include: set[Path]
    exclude: set[Path]
    re_include: re.Pattern | None
    re_exclude: re.Pattern | None
    size: list[tuple]
    archive: bool
    depth: int | None
    arc_ext: set[str]
    arc_exc_ext: set[str | None]
    arc_include: set[Path]
    arc_exclude: set[Path]
    arc_size: list[tuple]
    rar_backend: str | None
    absolute_path: bool
    paths_only: bool
    stats: bool
    
    def __post_init__(self):
        """Post-initialization processing to normalize and validate inputs"""
        self.path = Path(self.path)
        
        # If no search type is specified, search in all types.
        if not any((self.file, self.directory, self.content)):
            self.file = self.directory = self.content = True
        
        # Normalize extensions
        self.ext = set(self.ext)
        self.exclude_ext = (
            set(self.exclude_ext) | {None}
            if self.exclude_ext
            else set()
        )
        self.arc_ext = set(self.arc_ext)
        self.arc_exc_ext = (
            set(self.arc_exc_ext) | {None}
            if self.arc_exc_ext
            else set()
        )
        
        # Normalize include and exclude paths
        self.include = normalize_paths(self.path, self.include, 'include')
        self.exclude = normalize_paths(self.path, self.exclude, 'exclude')
        self.arc_include = {Path(p) for p in self.arc_include}
        self.arc_exclude = {Path(p) for p in self.arc_exclude}
        
        # Compile regex patterns
        self.re_include = compile_regex(self.re_include)
        self.re_exclude = compile_regex(self.re_exclude)
        
        # Normalize sizes
        self.size = compile_sizes(self.size, 'size')
        self.arc_size = compile_sizes(self.arc_size, 'arc-size')


@dataclass
class SearchResult:
    path: str
    virtual_path: list[str] = field(default_factory=list, kw_only=True)


@dataclass
class FileDirResult(SearchResult):
    matches: list[tuple[int, int]] = field(default_factory=list, kw_only=True)


@dataclass
class LineMatch:
    number: int
    text: str
    matches: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class ContentResult(SearchResult):
    lines: list[LineMatch] = field(default_factory=list, kw_only=True)
