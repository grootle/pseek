import re
from pathlib import Path
from dataclasses import dataclass, field
from .utils import compile_regex


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
    max_size: float | None
    min_size: float | None
    archive: bool
    depth: int | None
    arc_ext: set[str]
    arc_exc_ext: set[str | None]
    arc_include: set[Path]
    arc_exclude: set[Path]
    arc_max: float | None
    arc_min: float | None
    rar_backend: str | None
    absolute_path: bool
    paths_only: bool
    
    def __post_init__(self):
        """Post-initialization processing to normalize and validate inputs"""
        self.path = Path(self.path)
        
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
        self.include = {Path(p).resolve() for p in self.include}
        self.exclude = {Path(p).resolve() for p in self.exclude}
        self.arc_include = {Path(p) for p in self.arc_include}
        self.arc_exclude = {Path(p) for p in self.arc_exclude}
        
        # Compile regex patterns
        self.re_include = compile_regex(self.re_include)
        self.re_exclude = compile_regex(self.re_exclude)


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
