import click
from .searcher import seek
from .utils import check_rar_backend
from .structs import SearchConfig
from concurrent.futures import ProcessPoolExecutor, TimeoutError


def merge_matches(matches: list[tuple[int, int]]):
    """Merge overlapping matches (for example, if one match was inside another match)"""
    merged = []
    for start, end in matches:
        if not merged or start > merged[-1][1]:  # No overlap
            merged.append((start, end))
        else:
            # Merge overlapping
            merged[-1] = (
                merged[-1][0],
                max(merged[-1][1], end)
            )
    
    return merged


def build_highlight(text, matches):
    """Build highlighted text"""
    parts = []
    last = 0

    for start, end in matches:
        parts.append(text[last:start])
        parts.append(click.style(text[start:end], fg='green'))
        last = end
    parts.append(text[last:])

    return ''.join(parts)


def echo(results: dict):
    """Display results with a specific format and color scheme"""
    INDENT = '  '
    LINE_INDENT = '    '

    for match_type, datas in results.items():
        if datas:
            RESULT_TITLES = {
                "file": "Files",
                "directory": "Directories",
                "content": "Contents"
            }
            click.secho(f'\n{RESULT_TITLES[match_type]}:', fg='yellow')

            for data in datas:
                if match_type == 'content':  # Print a content-search result and its matching lines
                    separator = click.style("::", fg="yellow")
                    # Print file path
                    click.echo(
                        INDENT + \
                        separator.join(
                            [click.style(data.path, fg="cyan"), *(
                                click.style(path, fg="cyan")
                                for path in data.virtual_path
                            )]
                        )
                    )
                    
                    # Print file lines
                    for line in data.lines:
                        matches = merge_matches(line.matches)
                        # Keep the original count so overlapping matches are still counted separately
                        count = len(line.matches)
                        
                        # Show a note if the pattern repeats 3 or more times
                        count_query = f' ({count} matches)' if count >= 3 else ''
                        
                        prefix = click.style(
                            f"Line {line.number}{count_query}: ",
                            fg="magenta",
                        )
                        output_line = prefix + build_highlight(line.text, matches)

                        click.echo(LINE_INDENT + output_line)
                    
                    # Print a blank line to separate results
                    if data.lines:
                        print()
                else:  # Print a file or directory match, including archive paths
                    matches = merge_matches(data.matches)
                    
                    if data.virtual_path:  # Render archive results
                        separator = click.style("::", fg="yellow")
                        virtual_file_name = build_highlight(
                            data.virtual_path[-1],
                            matches
                        )

                        click.echo(
                            INDENT + \
                            separator.join(
                                [data.path, *data.virtual_path[0:-1], virtual_file_name]
                            )
                        )
                    else:
                        click.echo(
                            INDENT + build_highlight(data.path, matches)
                        )


@click.command()
@click.argument('query')
@click.option('-p', '--path', type=click.Path(exists=True, file_okay=False, dir_okay=True),
              default='.', show_default=True, help='Base directory to search in.')
# Search type options
@click.option('-f', '--file', is_flag=True, help='Search only in file names.')
@click.option('-d', '--directory', is_flag=True, help='Search only in directory names.')
@click.option('-c', '--content', is_flag=True, help='Search within file contents.')
# Additional options
@click.option('-C', '--case-sensitive', is_flag=True,
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
@click.option('--timeout', type=click.INT,
              help='Stop the search after the specified number of seconds.')
@click.option('--fuzzy', is_flag=True, help='Enable fuzzy search (approximate matching). '
              'except when --expr is enabled, '
              'in which case you can make it fuzzy by putting f before term: f"foo"')
@click.option('--fuzzy-level', type=click.IntRange(1, 99), default=80, show_default=True,
              help='Fuzzy matching threshold (1-99). Higher values require closer matches.')
# Extension filters
@click.option('--ext', multiple=True, type=click.STRING,
              help='Include files with these extensions. Example: --ext py --ext js')
@click.option('-E', '--exclude-ext', multiple=True, type=click.STRING,
              help='Exclude files with these extensions. Example: --exclude-ext jpg --exclude-ext exe')
# Include/Exclude specific paths (files or directories)
@click.option('-i', '--include', type=click.Path(exists=True, file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to include in search.')
@click.option('-e', '--exclude', type=click.Path(exists=True, file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to exclude from search.')
@click.option('--re-include', type=click.STRING,
              help='Directories or files to include in search with regex.')
@click.option('--re-exclude', type=click.STRING,
              help='Directories or files to exclude from search with regex.')
# Size filters
@click.option('--max-size', type=click.FLOAT, help='Maximum file/directory size (in MB).')
@click.option('--min-size', type=click.FLOAT, help='Minimum file/directory size (in MB).')
# Archive options
@click.option('--archive', is_flag=True,
              help='Enable search within archive files (e.g. zip, rar, 7z, gz, bz2, xz, tar, tar.gz, tar.bz2, tar.xz)')
@click.option('--depth', type=click.IntRange(min=0), show_default=True,
              help='Maximum nested archive depth. Example: 2 allows searching up to two archive levels.')
@click.option('--arc-ext', multiple=True, type=click.STRING,
              help='Include files with these extensions inside archive files. Example: --arc-ext py --arc-ext js')
@click.option('--arc-exc-ext', multiple=True, type=click.STRING,
              help='Exclude files with these extensions inside archive files. Example: --arc-exc-ext jpg --arc-exc-ext exe')
@click.option('--arc-include', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to include in search for inside archive files.')
@click.option('--arc-exclude', type=click.Path(file_okay=True, dir_okay=True),
              multiple=True, help='Directories or files to exclude from search for inside archive files.')
@click.option('--arc-max', type=click.FLOAT, help='Maximum size of files in the archive (in MB).')
@click.option('--arc-min', type=click.FLOAT, help='Minimum size of files in the archive (in MB).')
@click.option('--rar-backend', type=click.Path(exists=True, file_okay=True, dir_okay=False),
              help='Path to RAR backend tool (e.g. UnRAR.exe, ...). '
                   'Enter the file type in the query (e.g. unrar, bsdtar, unar, 7z).')
# Output option
@click.option('-a', '--absolute-path', is_flag=True, help='Display full paths for results.')
@click.option('--paths-only', is_flag=True, help='Only show matching file paths for content search.')
def search(**kwargs):
    """Search for files, directories, and file content based on the query."""

    config = SearchConfig(**kwargs)

    check_rar_backend(config.archive, config.rar_backend, config.query)

    if not config.expr and config.fuzzy:
        if not config.word:
            click.secho(
                "Warning: Fuzzy substring highlighting and counting matches are disabled to improve performance.",
                fg="yellow"
            )
        elif config.word and " " in config.query:
            click.secho(
                'Warning: When using "--fuzzy" and "--word", it is better to have the query be a word and '
                'not a phrase, as this will cause errors in the results.',
                fg="yellow"
            )

    # If no search type is specified, search in all types.
    if not any((config.file, config.directory, config.content)):
        config.file = config.directory = config.content = True

    # Stop search if it exceeds timeout (It doesn't kill the func and the func continues to execute in the background)
    if config.timeout:
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(seek, config)
            try:
                result = future.result(timeout=config.timeout)
                echo(result)
            except TimeoutError:
                click.secho(
                    f"Timeout! Search exceeded {config.timeout} seconds and was stopped.",
                    fg="red"
                )
    else:
        echo(seek(config))


if __name__ == "__main__":
    search()
