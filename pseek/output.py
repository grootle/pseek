import os

import click


def merge_matches(matches: list[tuple[int, int]]):
    """Merge overlapping matches (for example, if one match was inside another match)"""

    # sort by start position
    matches.sort()

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
        parts.append(click.style(text[start:end], fg='red', bold=True))
        last = end
    parts.append(text[last:])

    return ''.join(parts)


def path_sort_key(data):
    value = '::'.join((data.path, *data.virtual_path))
    # Normalize case on case-insensitive platforms.
    # If the normcase paths are identical,
    # use the original value for comparison.
    return os.path.normcase(value), value


def sort_results(sortby: str, datas: list, match_type: str):
    match sortby:
        case 'path':
            datas.sort(key=path_sort_key)
        case _:
            pass


def echo(results: dict, context: tuple[int, int], sortby: str):
    """Display results with a specific format and color scheme"""
    for match_type, datas in results.items():
        if datas:
            sort_results(sortby, datas, match_type)

            RESULT_TITLES = {
                "file": "Files",
                "directory": "Directories",
                "content": "Contents"
            }
            click.secho(f'\n{RESULT_TITLES[match_type]}\n────────────────', fg='yellow')

            for data in datas:
                if match_type == 'content':  # Print a content-search result and its matching lines
                    separator = click.style("::", fg="yellow")
                    # Print file path
                    click.echo(
                        separator.join(
                            [click.style(data.path, fg="cyan"), *(
                                click.style(path, fg="cyan")
                                for path in data.virtual_path
                            )]
                        )
                    )

                    counter = 0
                    for group in data.groups:
                        if any(context):
                            if counter != 0:
                                print('---')
                            else:
                                counter = 1

                        for line in group.lines:
                            if line.number in group.matching_lines:
                                matches = merge_matches(line.matches)

                            prefix = click.style(
                                f'{line.number}' + (':' if line.number in group.matching_lines else '-'),
                                fg='magenta'
                            )
                            output_line = prefix + (build_highlight(line.text, matches) \
                                if line.number in group.matching_lines \
                                else line.text)

                            print(output_line)

                    # Print a blank line to separate results
                    if data.groups:
                        print()
                else:  # Print a file or directory match, including archive paths
                    matches = merge_matches(data.matches)
                    
                    if data.virtual_path:  # Render archive results
                        separator = click.style("::", fg="yellow")
                        virtual_file_name = build_highlight(
                            data.virtual_path[-1],
                            matches
                        )

                        print(
                            separator.join(
                                [data.path, *data.virtual_path[0:-1], virtual_file_name]
                            )
                        )
                    else:
                        print(
                            build_highlight(data.path, matches)
                        )


def echo_stats(config, results, metrics, elapsed_time=None):
    """Render stats in a specific format and color scheme for display in the terminal"""
    
    INDENT = '  '
    click.secho('\nStatistics\n────────────────', fg='yellow')

    click.secho('Results', fg="cyan")
    if config.file:
        click.echo(INDENT + f'Files matched: {len(results["file"]):,}')
    
    if config.directory:
        click.echo(INDENT + f'Directories matched: {len(results["directory"]):,}')

    if config.content:
        click.echo(INDENT + f'Files with matched content: {len(results["content"]):,}')
        
        lines_matched = sum(len(group.matching_lines) for file in results["content"] for group in file.groups)
        matches = sum(
            len(line.matches)
            for file in results["content"]
            for group in file.groups for line in group.lines
        )
        
        if lines_matched:
            click.echo(INDENT + f"Lines matched: {lines_matched:,}")
        if matches:
            click.echo(INDENT + f"Matches: {matches:,}")
    
    click.secho('\nSearch', fg="cyan")
    if config.file or config.content:
        click.echo(INDENT + f"Files scanned: {len(metrics['files_scanned']):,}")
    if config.archive:
        click.echo(INDENT + f"Archives scanned: {len(metrics['archives_scanned']):,}")
    click.echo(INDENT + f"Directories scanned: {len(metrics['directories_scanned']):,}")
    
    click.echo(click.style("\nSearch time: ", fg='magenta') + f'{elapsed_time:.6f}s')
