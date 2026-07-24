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

pip install click==8.1.8 lark==1.2.2 py7zr==1.0.0 rarfile==4.2 rapidfuzz==3.13.0
```

## Basic Usage

```bash
psk <query> [options]
```

Example:

```bash
psk "error"
```

If no search type is specified, Pseek searches:

- File names
- Directory names
- File contents

simultaneously.

## Command Options

| Option                           | Description                                                                                                                                                                                                                                                      |
|----------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--path`                         | Base directory to search in (default: current directory `.`)                                                                                                                                                                                                     |
| `--file`                         | Search only in file names                                                                                                                                                                                                                                        |
| `--directory`                    | Search only in directory names                                                                                                                                                                                                                                   |
| `--content`                      | Search within file contents                                                                                                                                                                                                                                      |
| `--ext`, `--exclude-ext`         | Filter by file extension (e.g., `txt`, `log`)                                                                                                                                                                                                                    |
| `--case-sensitive`               | Make the search case-sensitive (except when `--expr` is enabled, in which case you can make it case sensitive by putting `c` before term: `c"foo"`)                                                                                                              |
| `--regex`                        | Use regular expressions to search (except when `--expr` is enabled, in which case you can make it regex by putting `r` before term: `r"foo"`)                                                                                                                    |
| `--include`, `--exclude`         | Limit search results to specific set of directories or files                                                                                                                                                                                                     |
| `--re-include`, `--re-exclude`   | Limit search results to specific directories or files with regex                                                                                                                                                                                                 |
| `--word`                         | Match the whole word only (except when `--expr` is enabled, in which case you can make it match whole word by putting `w` before term: `w"foo"`)                                                                                                                 |
| `--expr`                         | Enable boolean query expressions. Example: `r"foo.*bar" and ("bar" or "baz") and not "qux"`. Prefixes: `r=regex`, `c=case-sensitive`, `w=whole-word`, `f=fuzzy`                                                                                                  |
| `--timeout`                      | Stop the search after the specified number of seconds                                                                                                                                                                                                            |
| `--fuzzy`                        | Enable fuzzy search (Highlighting and counting matches are disabled in this mode if `--word` is not enabled to prevent the program from slowing down). except when `--expr` is enabled, in which case you can make it fuzzy by putting `f` before term: `f"foo"` |
| `--fuzzy-level`                  | Fuzzy matching threshold (0-99). Higher values require closer matches (default: `80`)                                                                                                                                                                            |
| `--max-size`, `--min-size`       | Specify maximum and minimum sizes for files and directories                                                                                                                                                                                                      |
| `--archive`                      | Enable search within archive files (e.g. `zip`, `rar`, `7z`, `gz`, `bz2`, `xz`, `tar`, `tar.gz`, `tar.bz2`, `tar.xz`)                                                                                                                                            |
| `--depth`                        | Maximum nested archive depth. Example: 2 allows searching up to two archive levels                                                                                                                                                                               |
| `--arc-ext`, `--arc-exc-ext`     | Filter by file extension inside archive files                                                                                                                                                                                                                    |
| `--arc-include`, `--arc-exclude` | Limit search results to specific set of directories or files inside archive files                                                                                                                                                                                |
| `--arc-max`, `--arc-min`         | Specify maximum and minimum sizes for files inside archive files (It doesn't work for directories because their size is zero in archive files)                                                                                                                   |
| `--rar-backend`                  | Path to RAR backend tool (e.g. UnRAR.exe, ...)                                                                                                                                                                                                                   |
| `--full-path`                    | Display full path of files and directories                                                                                                                                                                                                                       |
| `--paths-only`                   | Only show matching file paths for content search                                                                                                                                                                                                                 |

## Search Types

### Search File Names

```bash
psk "config" --file
```

### Search Directory Names

```bash
psk "backup" --directory
```

### Search File Contents

```bash
psk "TODO" --content
```

### Search Everywhere

```bash
psk "error"
```

Equivalent to:

```bash
psk "error" --file --directory --content
```

## Query Modes

By default, the query is treated as plain text.

Example:

```bash
psk "hello world"
```

### Case Sensitive Search

```bash
psk "Hello" --case-sensitive
```

Matches:

```text
Hello
```

Does not match:

```text
hello
HELLO
```

### Whole Word Search

```bash
psk "cat" --word
```

Matches:

```text
cat
```

Does not match:

```text
cats
concatenate
```

### Regular Expression Search

Enable regex mode:

```bash
psk "error\d+" --regex
```

Example matches:

```text
error1
error25
error999
```

## Fuzzy Search

Fuzzy search allows approximate matching.

Example:

```bash
psk "apple" --fuzzy
```

Can match:

```text
appl
appel
aple
```

### Fuzzy Similarity Threshold

```bash
psk "apple" --fuzzy --fuzzy-level 90
```

Range: `0-99`

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

## Extension Filters

Include only specific extensions:

```bash
psk "TODO" --ext py --ext js
```

Exclude extensions:

```bash
psk "TODO" --exclude-ext exe --exclude-ext dll
```

## Path Filters

### Include Paths

```bash
psk "TODO" \
    --include src \
    --include tests
```

Only search inside those paths.

### Exclude Paths

```bash
psk "TODO" \
    --exclude build \
    --exclude .git
```

Skip those paths.

## Regex Path Filters

### Include

```bash
psk "TODO" \
    --re-include "src/.*"
```

### Exclude

```bash
psk "TODO" \
    --re-exclude "node_modules|dist"
```

## Size Filters

Limit search by size.

Maximum:

```bash
psk "TODO" --max-size 100
```

Only search files/directories up to: `100 MB`

Minimum:

```bash
psk "TODO" --min-size 10
```

Only search files/directories larger than: `10 MB`

## Archive Search

Enable archive support:

```bash
psk "TODO" --archive
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

Limit recursion depth:

```bash
psk "TODO" --archive --depth 2
```

Meaning:

```text
archive level 1
archive level 2
```

will be searched.

Deeper levels will be skipped.

## Archive Filters

### Extension Filters

```bash
psk "TODO" --archive --arc-ext py
```

Only search `.py` files inside archives.

```bash
psk "TODO" --archive --arc-exc-ext jpg
```

Exclude `.jpg` files inside archives.

### Path Filters

Include:

```bash
psk "TODO" --archive --arc-include src
```

Exclude:

```bash
psk "TODO" --archive --arc-exclude cache
```

### Size Filters

Maximum:

```bash
psk "TODO" --archive --arc-max 10
```

Minimum:

```bash
psk "TODO" --archive --arc-min 1
```

Values are in MB.

**Note:** Archive directory sizes are usually reported as zero by archive formats, therefore archive size filtering is mainly useful for files.

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

- Linux: `psk "unrar" --rar-backend /usr/bin/unrar`
- Windows: `psk "unrar" --rar-backend "C:\Program Files\WinRAR\UnRAR.exe"`

Enter the file type in the query (e.g. `unrar`, `bsdtar`, `unar`, `7z`).

## Output Options

### Show Full Paths

```bash
psk "TODO" --full-path
```

### Paths Only

Only display matching file paths:

```bash
psk "TODO" --content --paths-only
```

Useful for very large result sets.

## Timeout

Stop the search automatically after a specified number of seconds.

Example:

```bash
psk "TODO" --timeout 30
```

If the search exceeds the limit, it will be terminated.

## Requirements

* Python `3.10+`
* `unrar`, `bsdtar`, `unar` or `7zip` for the [rarfile](https://pypi.org/project/rarfile/) library to support searching inside `.rar` files (optional)
