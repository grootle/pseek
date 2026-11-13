import click

from .sorting import sort_results


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


def convert_size(size_bytes: int) -> str:
    if size_bytes < 0:
        raise ValueError('Size cannot be negative')

    units = ('B', 'KiB', 'MiB', 'GiB', 'TiB',
             'PiB', 'EiB', 'ZiB', 'YiB')

    if size_bytes < 1024:
        return f'{size_bytes} B'

    i = min(
        # Implement log2 using the bit-length of the number.
        # 1024 has length of 11 bits. 1024**2 = 21 bits ...
        (size_bytes.bit_length() - 1) // 10,
        len(units) - 1
    )

    # 1 << (10 * i) == 1024**i (Left bit shift)
    # It shifts 1 to left by (10 * i) positions
    # and places the same number of 0s on right.
    # Each 0 means the number is multiplied by 2.
    size = size_bytes / (1 << (10 * i))

    # Avoid displaying 1024.00 KiB instead of 1.00 MiB.
    if i < len(units) - 1 and round(size, 2) >= 1024:
        i += 1
        size = size_bytes / (1 << (10 * i))

    return f'{size:.2f} {units[i]}'


def echo(results: dict, config):
    """Display results with a specific format and color scheme"""
    for match_type, datas in results.items():
        if datas:
            sort_results(config.sortby, config.sort_rev, datas, match_type)

            RESULT_TITLES = {
                "file": "Files",
                "directory": "Directories",
                "content": "Contents"
            }
            click.secho(f'\n{RESULT_TITLES[match_type]}\n────────────────', fg='yellow')

            for data in datas:
                if match_type == 'content':  # Print a content-search result and its matching lines
                    # Print file path
                    if data.virtual_path:
                        separator = click.style("::", fg="yellow")
                        click.echo(
                            separator.join(
                                [
                                    click.style(data.path, fg="cyan"),
                                    *(
                                        click.style(path, fg="cyan")
                                        for path in data.virtual_path[:-1]
                                    ),
                                    click.style(data.virtual_path[-1].string, fg="cyan")
                                ]
                            ) + ( 
                                ' - ' + convert_size(data.virtual_path[-1].size)
                                if config.show_size else ''
                            )
                        )
                    else:
                        click.echo(
                            click.style(data.path.string, fg="cyan") + ( 
                                ' - ' + convert_size(data.path.size)
                                if config.show_size else ''
                            )
                        )

                    counter = 0
                    for group in data.groups:
                        if any(config.context):
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
                            data.virtual_path[-1].string,
                            matches
                        )

                        print(
                            separator.join(
                                [data.path, *data.virtual_path[0:-1], virtual_file_name]
                            ) + ( 
                                ' - ' + convert_size(data.virtual_path[-1].size)
                                if config.show_size and not data.virtual_path[-1].is_dir else ''
                            )
                        )
                    else:
                        print(
                            build_highlight(data.path.string, matches) + ( 
                                ' - ' + convert_size(data.path.size)
                                if config.show_size and not data.path.is_dir else ''
                            )
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
