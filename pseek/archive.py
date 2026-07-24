import io
from click import style
from pathlib import Path
from .utils import get_archive_path_size, get_path_suffix, EXCLUDED_EXTENSIONS
# Archive modules
import zipfile, py7zr, tarfile, gzip, bz2, lzma, rarfile

# Archive extensions that are allowed
ARCHIVE_EXTS = ('zip', 'rar', '7z', 'tar', 'tar.gz', 'tar.bz2', 'tar.xz', 'gz', 'bz2', 'xz')


def archive_should_skip(path_info: Path, config, p_size: float, file_ext):
    """Check whether the file/directory inside archive files should be skipped based on various filters"""

    if (config.arc_include and not any(path_info.is_relative_to(inc) for inc in config.arc_include)) \
            or (config.arc_exclude and any(path_info.is_relative_to(exc) for exc in config.arc_exclude)) \
            or (config.arc_ext and file_ext not in config.arc_ext) \
            or (config.arc_exc_ext and file_ext in config.arc_exc_ext) \
            or (config.arc_max and p_size > config.arc_max) \
            or (config.arc_min and p_size < config.arc_min):
        return True

    if config.re_include:
        return not config.re_include.search(str(path_info))
    if config.re_exclude:
        return config.re_exclude.search(str(path_info)) is not None

    return False


def extract_names_from_archive(file_path: Path, config, depth: int | None = None,
                               file_bytes: bytes | None = None, parent_label: str = ''):
    """
    Recursively extract files and directories name from archive files.
    Supports nested archives like a.zip::b.7z::c.txt.

    Parameters:
        file_path (Path): the archive file path
        depth (int): the depth value that is returned recursively
        file_bytes (bytes | None): optional byte data if already read (for recursion)
        parent_label (str): string for nested archive tracking like a.zip::b.7z::file.txt

    Yields:
        tuple[str, Path, bool]: parent label, file or directory name, is directory
    """

    file_ext = get_path_suffix(file_path)
    label_prefix = (parent_label + str(file_path) + style('::', fg='yellow')) if parent_label else style('::', fg='yellow')
    if depth is None:
            depth = config.depth

    try:
        # Decide the stream source: from disk or memory
        file_stream = io.BytesIO(file_bytes) if file_bytes is not None else open(file_path, 'rb')

        # Handle ZIP and RAR archives
        if file_ext in ('zip', 'rar'):
            opener = {'zip': zipfile.ZipFile, 'rar': rarfile.RarFile}[file_ext]
            with opener(file_stream) as f:
                for info in f.infolist():
                    name = Path(info.filename)
                    new_path_ext = get_path_suffix(name)
                    if not archive_should_skip(
                            name,
                            config,
                            get_archive_path_size(info, file_ext),
                            new_path_ext
                    ):
                        yield label_prefix, name, info.is_dir()

                    # At each recursion, subtract 1 from depth if it's set
                    new_depth = None if depth is None else depth - 1
                    # Check if this is a nested archive
                    if new_path_ext in ARCHIVE_EXTS[:-3] and (new_depth is None or new_depth >= 0):
                        yield from extract_names_from_archive(
                            name,
                            config,
                            new_depth,
                            f.read(info),
                            label_prefix
                        )
        # Handle 7Z archives
        elif file_ext == '7z':
            with py7zr.SevenZipFile(file_stream, mode='r') as z:
                for info in z.list():
                    name = Path(info.filename)
                    new_path_ext = get_path_suffix(name)
                    if not archive_should_skip(
                            name,
                            config,
                            get_archive_path_size(info, '7z'),
                            new_path_ext
                    ):
                        yield label_prefix, name, info.is_directory

                    new_depth = None if depth is None else depth - 1
                    if new_path_ext in ARCHIVE_EXTS[:-3] and (new_depth is None or new_depth >= 0):
                        file_data = z.read([info.filename]).get(info.filename)
                        if file_data is None:
                            continue

                        yield from extract_names_from_archive(
                            name,
                            config,
                            new_depth,
                            file_data.read(),
                            label_prefix
                        )
        # Handle TAR and compressed TAR formats
        elif file_ext in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
            # Specify the mode based on the file ext to open it
            mode = {
                'tar': 'r',
                'tar.gz': 'r:gz',
                'tar.bz2': 'r:bz2',
                'tar.xz': 'r:xz'
            }[file_ext]

            with tarfile.open(fileobj=file_stream, mode=mode) as tf:
                for member in tf.getmembers():
                    name = Path(member.name)
                    new_path_ext = get_path_suffix(name)
                    if not archive_should_skip(
                            name,
                            config,
                            get_archive_path_size(member, file_ext),
                            new_path_ext
                    ):
                        yield label_prefix, name, member.isdir()

                    new_depth = None if depth is None else depth - 1
                    if new_path_ext in ARCHIVE_EXTS[:-3] and (new_depth is None or new_depth >= 0):
                        f = tf.extractfile(member)
                        if f is None:
                            continue

                        yield from extract_names_from_archive(
                            name,
                            config,
                            new_depth,
                            f.read(),
                            label_prefix
                        )
    except Exception:
        return  # silently skip invalid archives


def extract_text_from_archive(file_path: Path, config, depth: int | None = None,
                              file_bytes: bytes | None = None, parent_label: str = ''):
    """
    Recursively extract (path_label, text_content) from any archive file.
    Supports nested archives like a.zip::b.7z::c.txt.

    Parameters:
        file_path (Path): the archive file path
        depth (int): the depth value that is returned recursively
        file_bytes (bytes | None): optional byte data if already read (for recursion)
        parent_label (str): string for nested archive tracking like a.zip::b.7z::file.txt

    Yields:
        (str, str): tuple of full virtual path and decoded content text
    """

    file_ext = get_path_suffix(file_path)
    label_prefix = (parent_label + str(file_path) + '::') if parent_label else '::'
    if depth is None:
            depth = config.depth

    try:
        # Decide the stream source: from disk or memory
        file_stream = io.BytesIO(file_bytes) if file_bytes is not None else open(file_path, 'rb')

        # Handle ZIP and RAR archives
        if file_ext in ('zip', 'rar'):
            opener = {'zip': zipfile.ZipFile, 'rar': rarfile.RarFile}[file_ext]
            with opener(file_stream) as f:
                for info in f.infolist():
                    file_name = Path(info.filename)
                    data = f.read(info)
                    # At each recursion, subtract 1 from depth if it's set
                    new_depth = None if depth is None else depth - 1
                    new_path_ext = get_path_suffix(file_name)

                    # Check if this is a nested archive
                    if new_path_ext in ARCHIVE_EXTS and (new_depth is None or new_depth >= 0):
                        yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    else:
                        if archive_should_skip(
                                file_name,
                                config,
                                get_archive_path_size(info, file_ext),
                                new_path_ext
                        ) or info.is_dir() or new_path_ext in EXCLUDED_EXTENSIONS:
                            continue

                        yield label_prefix + str(file_name), data
        # Handle 7Z archives
        elif file_ext == '7z':
            with py7zr.SevenZipFile(file_stream, mode='r') as archive:
                for info in archive.list():
                    file_data = archive.read([info.filename]).get(info.filename)
                    if file_data is None:
                        continue

                    file_name = Path(info.filename)
                    data = file_data.read()
                    new_depth = None if depth is None else depth - 1
                    new_path_ext = get_path_suffix(file_name)

                    if new_path_ext in ARCHIVE_EXTS and (new_depth is None or new_depth >= 0):
                        yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    else:
                        if archive_should_skip(
                                file_name,
                                config,
                                get_archive_path_size(info, '7z'),
                                new_path_ext
                        ) or info.is_directory or new_path_ext in EXCLUDED_EXTENSIONS:
                            continue

                        yield label_prefix + str(file_name), data
        # Handle TAR and compressed TAR formats
        elif file_ext in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
            mode = {
                'tar': 'r',
                'tar.gz': 'r:gz',
                'tar.bz2': 'r:bz2',
                'tar.xz': 'r:xz'
            }[file_ext]

            with tarfile.open(fileobj=file_stream, mode=mode) as tf:
                for member in tf.getmembers():
                    f = tf.extractfile(member)
                    if f is None:
                        continue

                    file_name = Path(member.name)
                    data = f.read()
                    new_depth = None if depth is None else depth - 1
                    new_path_ext = get_path_suffix(file_name)

                    if new_path_ext in ARCHIVE_EXTS and (new_depth is None or new_depth >= 0):
                        yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    else:
                        if archive_should_skip(
                                file_name,
                                config,
                                get_archive_path_size(member, file_ext),
                                new_path_ext
                        ) or member.isdir() or new_path_ext in EXCLUDED_EXTENSIONS:
                            continue

                        yield label_prefix + str(file_name), data
        # Handle single compressed files like .gz, .bz2, .xz
        elif file_ext in ARCHIVE_EXTS[-3:]:
            opener = {'gz': gzip.open, 'bz2': bz2.open, 'xz': lzma.open}[file_ext]
            with opener(file_stream, 'rb') as f:
                yield label_prefix[:-2], f.read()
    except Exception:
        return
