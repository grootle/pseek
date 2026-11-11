import platform
import shutil
import time
from pathlib import Path

import click
import rarfile

from .core.search.parallel import seek
from .core.search.timeout import search_with_timeout
from .output import echo, echo_stats
from .structs import SearchConfig

BACKEND_PATH = Path(__file__).parent / "RARBackend"


def check_rar_backend(archive_enabled: bool, tool_path: str | None, backend: str):
    """Check for the existence of rar backend or save and set it for rarfile"""

    # Save backend path for later executions
    if tool_path:
        if backend in ('unrar', 'bsdtar', 'unar', '7z'):
            with open(BACKEND_PATH, 'w') as f:
                f.write(f'{backend}:{tool_path}')
            click.secho(f"RAR backend set to: {backend} -> {tool_path}", fg="green")
        else:
            click.secho("Unknown RAR backend tool. Please provide one of: unrar, bsdtar, unar, 7z.", fg="red")
        raise click.exceptions.Exit(1)

    if archive_enabled:
        # Try to detect presence of RAR backends in PATH
        unrar_path = shutil.which('unrar')
        bsdtar_path = shutil.which('bsdtar')
        sevenzip_path = shutil.which('7z') or shutil.which('7za')  # Some versions are in 7za format
        unar_path = shutil.which('unar')

        if not any((unrar_path, bsdtar_path, sevenzip_path, unar_path)) and not BACKEND_PATH.exists():
            system = platform.system()
            if system == 'Linux':
                install_tip = "sudo apt install unrar"
            elif system == 'Darwin':
                install_tip = "brew install unrar"
            else:
                install_tip = "Download from https://www.rarlab.com/download.htm"

            click.secho(
                "Warning: unrar, bsdtar, 7zip or unar is not installed on system or "
                "it is not in the system PATH.\nRAR archive support is disabled.\n"
                "To enable RAR support, please install one of them. For example:\n"
                f"  - {install_tip}\n"
                "If it is installed or in the system PATH and you still have problems, use this option: '--rar-backend'\n",
                fg='yellow'
            )
        elif BACKEND_PATH.exists():
            with open(BACKEND_PATH, 'r') as f:
                b, tool = f.read().split(':', 1)

            # Set up the backend for rarfile
            match b:
                case 'unrar':
                    rarfile.UNRAR_TOOL = tool
                case 'bsdtar':
                    rarfile.BSDTAR_TOOL = tool
                case 'unar':
                    rarfile.UNAR_TOOL = tool
                case '7z':
                    rarfile.SEVENZIP_TOOL = tool


@click.command()
@click.argument('query', required=False)
@click.argument('path', type=click.Path(exists=True, file_okay=False, dir_okay=True),
                default='.', required=False)
# Search type options
@click.option('-f', '--file', is_flag=True, help='Search only in file names.')
@click.option('-d', '--directory', is_flag=True, help='Search only in directory names.')
@click.option('-c', '--content', is_flag=True, help='Search within file contents.')
# Additional options
@click.option('-s', '--case-sensitive', is_flag=True,
              help='Make the search case-sensitive '
                   '(except when --expr is enabled, '
                   'in which case you can make it case sensitive by putting c before term: c"foo")')
@click.option('-r', '--regex', is_flag=True,
              help='Use regular expressions to search '
                   '(except when --expr is enabled, '
                   'in which case you can make it regex by putting r before term: r"foo")')
@click.option('-w', '--word', is_flag=True,
              help='Match whole words only '
                   '(except when --expr is enabled, '
                   'in which case you can make it match whole word by putting w before term: w"foo")')
@click.option('--expr', is_flag=True,
              help='Enable boolean query expressions. Example: r"foo.*bar" and ("bar" or "baz") and not "qux". '
                   'Prefixes: r=regex, c=case-sensitive, w=whole-word, f=fuzzy.')
@click.option('--fuzzy', is_flag=True, help='Enable fuzzy search (approximate matching). '
              'except when --expr is enabled, '
              'in which case you can make it fuzzy by putting f before term: f"foo"')
@click.option('--fuzzy-level', metavar='INTEGER', type=click.IntRange(1, 99), default=80, show_default=True,
              help='Fuzzy matching threshold (1-99). Higher values require closer matches.')
@click.option('-C', '--context', metavar='BEFORE:AFTER',
              help='Show N context lines before and after matches, or use N:M to specify before:after.')
@click.option('-p', '--full-path', is_flag=True,
              help='By default, query is only matched against the filename or directory name '
              '(this applies only when searching for files or directories, not file contents). '
              'Using this flag, query is matched against the full path '
              '(and, if --absolute-path flag is enabled, against the absolute path).')
@click.option('--line', is_flag=True,
              help='Match lines where the entire line participates in a match.')
@click.option('-D', '--depth', multiple=True, metavar='MIN:MAX',
              help='Limit directory traversal to given depth range. '
              'By default, there is no limit on search depth.')
# Automatic filtering
@click.option('-u', '--unrestricted', is_flag=True,
              help='Disable all automatic filters except the binary file filter for content search.')
@click.option('--no-ignore', is_flag=True,
              help='It disables all automatic filters related to git. '
              'This implies include --no-git-ignore, --no-ignore-dot, '
              '--no-ignore-exclude, --no-ignore-global, --no-ignore-parent')
@click.option('--no-git-ignore', is_flag=True, help="Don't respect filter rules from .gitignore files.")
@click.option('--no-ignore-dot', is_flag=True, help="Don't respect filter rules from .ignore files.")
@click.option('--no-ignore-exclude', is_flag=True,
              help="Don't respect filter rules from files that are manually configured for the repository. "
              "For example, this includes git's .git/info/exclude.")
@click.option('--no-ignore-global', is_flag=True,
              help="Don't respect filter rules from ignore files that come from \"global\" sources such as "
              "git's core.excludesFile configuration option (which defaults to $HOME/.config/git/ignore).")
@click.option('--no-ignore-parent', is_flag=True,
              help='When this flag is set, filter rules from ignore files found in parent '
              'directories are not respected. By default, Pseek will ascend the parent directories '
              'of the current working directory to look for any applicable ignore files that should be applied.')
@click.option('--no-require-git', is_flag=True,
              help='When this flag is given, source control ignore files such as '
              '.gitignore are respected even if no git repository is present.\n\n'
              'By default, Pseek will only respect filter rules from source control ignore files '
              'when Pseek detects that the search is executed inside a source control repository. '
              'For example, when a .git directory is observed.')
@click.option('-.', '--hidden', is_flag=True,
              help="Search hidden files and directories. By default, hidden files and directories are skipped. "
              "Note that if a hidden file or a directory is whitelisted in an ignore file, "
              "then it will be searched even if this flag isn't provided. Similarly if "
              "a hidden file or directory is given explicitly as path argument or include option.")
@click.option('--follow', is_flag=True,
              help='Follow symbolic links while traversing directories. This behavior is disabled by default. '
              'Symbolic link loops and broken links are automatically skipped. Symbolic links are given '
              'explicitly as path argument or include option then they will be searched even if this flag is disabled.')
@click.option('-g', '--glob', metavar='GLOB', multiple=True,
              help='Include or exclude files and directories for searching that match the given glob. '
              'This always overrides any other ignore logic. Multiple glob flags may be used. '
              'Globbing rules match .gitignore globs.')
# Extension filters
@click.option('--ext', multiple=True, type=click.STRING, metavar='EXTENSION',
              help='Include files with these extensions. Example: --ext py --ext js')
@click.option('-E', '--exclude-ext', multiple=True, type=click.STRING, metavar='EXTENSION',
              help='Exclude files with these extensions. Example: --exclude-ext jpg --exclude-ext exe')
# Include/Exclude specific paths (files or directories)
@click.option('-i', '--include', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to include in search.')
@click.option('-e', '--exclude', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to exclude from search.')
@click.option('--re-include', type=click.STRING, metavar='REGEX',
              help='Directories or files to include in search with regex.')
@click.option('--re-exclude', type=click.STRING, metavar='REGEX',
              help='Directories or files to exclude from search with regex.')
# Size filters
@click.option('--size', metavar='MIN:MAX', multiple=True, help='Limit results based on the size of files.')
# Archive options
@click.option('--archive', is_flag=True,
              help='Enable search within archive files (e.g. zip, rar, 7z, gz, bz2, xz, tar, tar.gz, tar.bz2, tar.xz)')
@click.option('--arc-depth', multiple=True, metavar='MIN:MAX',
              help='Limit nested archive to given depth range. By default, there is no limit.')
@click.option('--arc-ext', multiple=True, type=click.STRING, metavar='EXTENSION',
              help='Include files with these extensions inside archive files. Example: --arc-ext py --arc-ext js')
@click.option('--arc-exc-ext', multiple=True, type=click.STRING, metavar='EXTENSION',
              help='Exclude files with these extensions inside archive files. Example: --arc-exc-ext jpg --arc-exc-ext exe')
@click.option('--arc-include', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to include in search for inside archive files.')
@click.option('--arc-exclude', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to exclude from search for inside archive files.')
@click.option('--arc-size', multiple=True, metavar='MIN:MAX',
              help='Limit results based on the size of files in the archive.')
@click.option('--rar-backend', type=click.Path(exists=True, file_okay=True, dir_okay=False),
              help='Path to RAR backend tool (e.g. UnRAR.exe, ...). '
                   'Enter the file type in the query (e.g. unrar, bsdtar, unar, 7z).')
# Output option
@click.option('-a', '--absolute-path', is_flag=True, help='Display full paths for results.')
@click.option('-l', '--paths-only', is_flag=True, help='Only show matching file paths for content search.')
@click.option('-S', '--stats', is_flag=True,
              help='Show search statistics including result counts and search time.')
@click.option('--timeout', metavar='FLOAT',
              type=click.FloatRange(min=0, min_open=True),
              help='Stop the search after the specified number of seconds.')
@click.option('--sort', 'sortby', metavar='SORTBY',
              type=click.Choice(['none', 'path', 'size']),
              default='none', show_default=True)
@click.option('--threads', metavar='NUM', type=click.IntRange(min=0), default=0,
              help='This flag sets the approximate number of threads to use. '
              'A value of 0 (which is the default) causes pseek to choose the thread count using heuristics.')
def search(**kwargs):
    """Search for files, directories, and file content based on the query."""

    config = SearchConfig(**kwargs)

    check_rar_backend(config.archive, config.rar_backend, config.query)

    if not config.expr and config.fuzzy and not config.line:
        if not config.word:
            click.secho(
                "Warning: To improve performance, highlighting of matches is disabled.",
                fg="yellow"
            )
        elif config.word and " " in config.query:
            click.secho(
                'Warning: When using "--fuzzy" and "--word", it is better to have the query be a word and '
                'not a phrase, as this will cause errors in the results.',
                fg="yellow"
            )

    if config.timeout:
        results, metrics, elapsed, timed_out = search_with_timeout(config)

        # Even if the search timed out, display all results found before termination.
        echo(results, config.context, config.sortby)

        if timed_out:
            click.secho(
                f"\nTimeout! Search exceeded {config.timeout} seconds.",
                fg="red",
            )

        if config.stats:
            echo_stats(config, results, metrics, elapsed)
    else:
        start = time.perf_counter()
        results, metrics = seek(config)
        elapsed = time.perf_counter() - start
        
        echo(results, config.context, config.sortby)
        if config.stats:
            echo_stats(config, results, metrics, elapsed)


if __name__ == "__main__":
    search()
