import re, sys, click
from pathlib import Path

EXTENSIONS_PATH = Path(__file__).parent / "compound_extensions"
try:
    with open(EXTENSIONS_PATH, "r") as f:
        COMPOUND_EXTENSIONS = {line.strip() for line in f}
except FileNotFoundError:
    COMPOUND_EXTENSIONS = set()
    click.secho(
        f"Couldn't find compound_extensions at {EXTENSIONS_PATH}. The program may not work properly.",
        fg='yellow'
    )


def compile_regex(txt, flags=0) -> re.Pattern | None:
    if txt is not None:
        try:
            return re.compile(txt, flags)
        except re.error as e:
            click.secho(f"Regex compile error: {e}", fg='red')
            sys.exit(1)


def get_path_suffix(path: Path | str) -> str:
    """ If multiple file suffixes are valid, return them, otherwise return only the last suffix """
    if isinstance(path, str):
        path = Path(path)

    if path.is_dir():
        return None

    suffixes = ''.join(path.suffixes)[1:].lower()

    return (
        suffixes
        if suffixes in COMPOUND_EXTENSIONS
        else path.suffix[1:].lower()
    )


def is_binary(file) -> bool:
    """Check if a file is binary by reading the first 8 KiB and looking for null bytes."""
    if isinstance(file, Path):
        try:
            with file.open('rb') as f:
                return b'\x00' in f.read(8192)
        except OSError:
            return False
    else:
        return b'\x00' in file
