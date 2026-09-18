# Pseek

Fast and powerful command-line search tool for finding files, directories, and text content. 

## Features

* Search file names
* Search directory names
* Search file contents
* Search inside archive files
* Boolean query expressions (`and`, `or`, `not`)
* Regular expressions
* Fuzzy matching
* Whole-word matching
* Case-sensitive search
* Archive recursion depth control
* Extension filters
* Path filters
* Size filtering
* Full path output
* Highlight matches in output
* Cross-platform (Linux, macOS, Windows)

## Installation

### Install from PyPI (Recommended)

```bash
pip install pseek
```

### Install from Source

```bash
git clone https://github.com/grootle/pseek.git

cd pseek

python -m venv venv

# Activate virtual environment

pip install .
```

## Basic Usage

```bash
psk <query> <path> [options]
```

Example:

```bash
psk error
```

If no search type is specified, Pseek searches:

- File names
- Directory names
- File contents

simultaneously.

To search for a query that starts with `-`, use `--` to mark the end of options:

```bash
psk -- --path
```

## Command Options

| Option | Description |
| --- | --- |
| `--file` | Search only in file names |
| `--directory` | Search only in directory names |
| `--content` | Search within file contents |
| `--ext`, `--exclude-ext` | Filter by file extension (e.g., `txt`, `log`) |
| `--case-sensitive` | Make the search case-sensitive (except when `--expr` is enabled, in which case you can make it case sensitive by putting `c` before term: `c"foo"`) |
| `--regex` | Use regular expressions to search (except when `--expr` is enabled, in which case you can make it regex by putting `r` before term: `r"foo"`) |
| `--include`, `--exclude` | Limit search results to specific set of directories or files |
| `--re-include`, `--re-exclude` | Limit search results to specific directories or files with regex |
| `--word` | Match the whole word only (except when `--expr` is enabled, in which case you can make it match whole word by putting `w` before term: `w"foo"`) |
| `--expr` | Enable boolean query expressions. Example: `r"foo.*bar" and ("bar" or "baz") and not "qux"`. Prefixes: `r=regex`, `c=case-sensitive`, `w=whole-word`, `f=fuzzy` |
| `--context` | Show N context lines before and after matches, or use N:M to specify before:after |
| `--depth` | Limit directory traversal to given depth range. By default, there is no limit on search depth |
| `--timeout` | Stop the search after the specified number of seconds |
| `--fuzzy` | Enable fuzzy search (Highlighting and counting matches are disabled in this mode if `--word` is not enabled to prevent the program from slowing down). except when `--expr` is enabled, in which case you can make it fuzzy by putting `f` before term: `f"foo"` |
| `--fuzzy-level` | Fuzzy matching threshold (0-99). Higher values require closer matches (default: `80`) |
| `--size` | Limit results based on the size of files |
| `--archive` | Enable search within archive files (e.g. `zip`, `rar`, `7z`, `gz`, `bz2`, `xz`, `tar`, `tar.gz`, `tar.bz2`, `tar.xz`) |
| `--arc-depth` | Limit nested archive to given depth range. By default, there is no limit |
| `--arc-ext`, `--arc-exc-ext` | Filter by file extension inside archive files |
| `--arc-include`, `--arc-exclude` | Limit search results to specific set of directories or files inside archive files |
| `--arc-size` | Limit results based on the size of files in the archive |
| `--rar-backend` | Path to RAR backend tool (e.g. UnRAR.exe, ...) |
| `--absolute-path` | Display full path of files and directories |
| `--paths-only` | Only show matching file paths for content search |
| `--stats` | Show search statistics including result counts and search time |

## Specifying the root directory

To search a specific directory, path can be given as a second argument:

```bash
psk error /log
```

## Search Types

### Search File Names

```bash
psk config --file
```

### Search Directory Names

```bash
psk backup --directory
```

### Search File Contents

```bash
psk TODO --content
```

### Search Everywhere

```bash
psk error
```

Equivalent to:

```bash
psk error --file --directory --content
```

## Query Modes

By default, the query is treated as plain text.

Example:

```bash
psk "hello world"
```

> **Note:** To use case-sensitive, whole-word matching, regular expression search, and fuzzy search when `--expr` is enabled, we can use [expression prefixes](#expression-prefixes).

### Case Sensitive Search

```bash
psk Hello --case-sensitive
```

Matches: `Hello`

Does not match: `hello`, `HELLO`

### Whole Word Search

```bash
psk cat --word
```

Matches: `cat`

Does not match: `cats`, `concatenate`

### Regular Expression Search

Enable regex mode:

```bash
psk error\d+ --regex
```

Example matches: `error1`, `error25`, `error999`

## Fuzzy Search

Fuzzy search allows approximate matching.

Example:

```bash
psk apple --fuzzy
```

Can match: `appl`, `appel`, `aple`

### Fuzzy Similarity Threshold

```bash
psk apple --fuzzy --fuzzy-level 90
```

Range: `1-99`

Higher values require closer matches.

Examples:

| Level | Strictness  |
|-------|-------------|
| 60    | Loose       |
| 80    | Recommended |
| 95    | Very strict |

Default: `80`

## Expression Queries

Expression mode enables logical search expressions.

Enable:

```bash
psk '("error" or "warning") and not "debug"' --expr
```

### Supported Operators

#### AND

```bash
psk '"foo" and "bar"' --expr
```

Both terms must match.

#### OR

```bash
psk '"foo" or "bar"' --expr
```

At least one term must match.

#### NOT

```bash
psk 'not "foo"' --expr
```

Exclude matches containing the term.

#### PARENTHESES

```bash
psk '("foo" or "bar") and not "baz"' --expr
```

Used for grouping expressions.

### Expression Prefixes

Each term can have its own search mode.

#### Regex

```text
r"pattern"
```

Example:

```bash
psk 'r"error\d+"' --expr
```

#### Case Sensitive

```text
c"text"
```

Example:

```bash
psk 'c"Error"' --expr
```

#### Whole Word

```text
w"text"
```

Example:

```bash
psk 'w"cat"' --expr
```

#### Fuzzy

```text
f"text"
```

Example:

```bash
psk 'f"apple"' --expr
```

### Combined Prefixes

Prefixes can be combined.

Examples:

```text
rc"text"
cw"text"
cf"text"
wcf"text"
```

Example:

```bash
psk 'rc"Error\d+"' --expr
```

Meaning:

- regex
- case-sensitive

simultaneously.

Allowed modes: `r`, `c`, `w`, `f`, `rc`, `cr`, `cw`, `wc`, `cf`, `fc`, `wf`, `fw`, `cwf`, `cfw`, `wcf`, `wfc`, `fcw`, `fwc`

> **Note:** Whole word matching and regex matching cannot be used at the same time, because we can use `\b` in regex to enable whole word matching: `r"\btext\b"`

## Context

Show context lines around each match. The value is specified as `BEFORE:AFTER`:

```bash
--context 2       # 2 lines before and after
--context 2:0     # 2 lines before, none after
--context 0:2     # none before, 2 lines after
--context 2:5     # 2 lines before, 5 lines after
--context 2:      # 2 lines before, none after
--context :2      # none before, 2 lines after
--context 0       # matching lines only
```

Nearby matches whose context ranges overlap or directly touch are combined into a single group.

## Depth

Controls how deep the search goes inside directories.

A depth of `0` means that only base path's immediate contents are searched; subdirectories are not entered.

```text
project/                  ← base directory
├── file.txt              ← depth 0
├── folder1/              ← depth 0
│   ├── file.txt          ← depth 1
│   └── folder2/          ← depth 1
│       └── file.txt      ← depth 2
```

`--depth` can be specified multiple times to search non-contiguous depth ranges:

```bash
--depth 0              # Direct contents only
--depth 1              # One level inside
--depth 2:4            # Depths 2 through 4
--depth 2 --depth 5:7  # Depths 2 and 5 through 7
--depth :2             # Depths 0 through 2
--depth 3:             # Depth 3 and deeper
```

If `--depth` is not specified, the search has no depth limit.

## Extension Filters

Include only specific extensions:

```bash
psk TODO --ext py --ext js
```

Exclude extensions:

```bash
psk TODO --exclude-ext exe --exclude-ext dll
```

## Path Filters

### Include Paths

```bash
psk TODO \
    --include src \
    --include tests
```

Only search inside those paths.

### Exclude Paths

```bash
psk TODO \
    --exclude build \
    --exclude .git
```

Skip those paths.

> **Note:** The include and exclude paths will be combined with path argument.

## Regex Path Filters

### Include

```bash
psk TODO \
    --re-include src/.*
```

### Exclude

```bash
psk TODO \
    --re-exclude "node_modules|dist"
```

## Size Filtering

| Syntax                    | Meaning                        |
| ------------------------- | ------------------------------ |
| `10m`                     | exactly `10 MiB`               |
| `:10m`                    | `10 MiB` or smaller            |
| `10m:`                    | `10 MiB` or larger             |
| `10m:20m`                 | between `10 MiB` and `20 MiB`  |

Both range boundaries are included.

Sizes can be specified using the following units:

| Suffix | Unit                 |
| ------ | -------------------- |
| `b`    | Bytes                |
| `k`    | KiB (`1024` bytes)   |
| `m`    | MiB (`1024^2` bytes) |
| `g`    | GiB (`1024^3` bytes) |
| `t`    | TiB (`1024^4` bytes) |

Unit suffixes are case-insensitive, so these are equivalent: `10m`, `10M`

The `--size` option can be used multiple times. Each size filter is treated as an alternative, meaning that a file only needs to match **one** of the specified ranges.

For example:

```bash
psk config \
    --size :1m \
    --size 10m:
```

Files between `1 MiB` and `10 MiB` will not match.

> **Note:** Directory sizes are not calculated recursively. When `--size` is used, directories are automatically excluded from the search results.

## Archive Search

Enable archive support:

```bash
psk TODO --archive
```

Supported formats: `zip`, `rar`, `7z`, `gz`, `bz2`, `xz`, `tar`, `tar.gz`, `tar.bz2`, `tar.xz`

### Nested Archives

Pseek supports nested archives for multi-file archive containers (zip, rar, 7z, tar and compressed tar formats). Nested archive traversal means Pseek can search inside an archive that itself contains other archives (for example `a.zip` containing `b.7z` containing `c.tar.gz`).

Example:

```text
backup.zip
 └── source.7z
      └── notes.txt
```

Pseek can search:

```text
backup.zip::source.7z::notes.txt
```

### Archive Depth

The concept of depth in archive is different from `--depth`. Depth in archive is calculated based on nested archives. Each archive that is inside another archive counts as one level of depth.

| Syntax | Meaning                                                  |
| ------ | -------------------------------------------------------- |
| `2`    | exactly `2nd` depth                                      |
| `:2`   | `2nd` depth or lower                                     |
| `2:`   | `2nd` depth or higher                                    |
| `2:4`  | between `2` and `4` (Both range boundaries are included) |

`--arc-depth` can be specified multiple times:

```bash
psk TODO --archive --arc-depth :2 --arc-depth 5:
```

Meaning `archive level 3` and `archive level 4` won't be searched.

> **Note:** `--arc-depth 0` means perform the search only within this current archive and don't enter nested archives.

## Archive Filters

### Extension Filters

```bash
psk TODO --archive --arc-ext py
```

Only search `.py` files inside archives.

```bash
psk TODO --archive --arc-exc-ext jpg
```

Exclude `.jpg` files inside archives.

### Path Filters

Include:

```bash
psk TODO --archive --arc-include src
```

Exclude:

```bash
psk TODO --archive --arc-exclude cache
```

### Size Filter

This works exactly like the [--size](#size-filtering) option.

```bash
psk TODO --archive --arc-size 10m:40m
```

> **Note:** Archive directory sizes are usually reported as zero by archive formats, so directory search is disabled if this filter is enabled to avoid incorrect results.

## RAR Backend

RAR archives require an external helper programs. To enable full support for RAR, either install one of the helper programs in your PATH or provide a backend configuration to Pseek.

Supported backends include:

- UnRAR
- 7-Zip
- BSDTar
- Unar

If one of these is installed and available in PATH, Pseek will detect it automatically when `--archive` is used and enable archive traversal for RAR files. If not detected, Pseek prints a warning and archive support for that format is disabled.

Use the `--rar-backend` option to persistently configure a backend and its path.

Examples:

- Linux: `psk unrar --rar-backend /usr/bin/unrar`
- Windows: `psk unrar --rar-backend "C:\Program Files\WinRAR\UnRAR.exe"`

Enter the file type in the query (e.g. `unrar`, `bsdtar`, `unar`, `7z`).

## Output Options

### Show Full Paths

```bash
psk TODO --absolute-path
```

### Paths Only

Only display matching file paths:

```bash
psk TODO --content --paths-only
```

Useful for very large result sets.

## Timeout

Stop the search automatically after a specified number of seconds.

Example:

```bash
psk TODO --timeout 0.5
```

If the search exceeds the limit, it will be terminated. Results found before the search is terminated are still displayed.

## Search Statistics

Display a summary of the search, including result counts, scanned paths, archive information, and search time.

```bash
pseek config --stats
```

Example output:

```text
Statistics
────────────────
Results
  Files: 12
  Directories matched: 3
  Files with matched content: 8
  Lines matched: 24
  Matches: 31

Search
  Files scanned: 1,248
  Archives scanned: 5
  Directories scanned: 96

Search time: 0.128s
```

### Result statistics

* **Files matched** — Number of files whose names matched the query.
* **Directories matched** — Number of directories whose names matched the query.
* **Files with matched content** — Number of files containing at least one content match.
* **Lines matched** — Number of lines containing one or more matches.
* **Matches** — Total number of matches found in the contents of the files.

### Search statistics

* **Files scanned** — Number of files examined during the search.
* **Archives scanned** — Number of archives processed, including nested archives found inside other archives.
* **Directories scanned** — Number of directories reached and examined during traversal.

When `--archive` is enabled, file and directory statistics can also include paths inside archives, not just physical paths on the filesystem.

`Directories scanned` can be `0` when the search path contains no subdirectories. The root search directory itself isn't counted as a scanned directory.

### Search time

Time spent performing the search.

When `--timeout` is used, the statistics represent the work completed before the timeout.

## Requirements

* Python `3.10+`
* `unrar`, `bsdtar`, `unar` or `7zip` for the [rarfile](https://pypi.org/project/rarfile/) library to support searching inside `.rar` files (optional)
