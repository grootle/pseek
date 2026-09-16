import io
from pathlib import Path
from .utils import get_path_suffix, is_binary
# Archive modules
import zipfile, py7zr, tarfile, gzip, bz2, lzma, rarfile

# Archive extensions that are allowed
ARCHIVE_EXTS = ('zip', 'rar', '7z', 'tar', 'tar.gz', 'tar.bz2', 'tar.xz', 'gz', 'bz2', 'xz')


def get_archive_path_size(info, file_type: str) -> int:
    """Get and return the size of the files inside the archive files"""
    if file_type in ('zip', 'rar'):
        return info.file_size
    elif file_type == '7z':
        return info.uncompressed
    elif file_type in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
        return info.size


def archive_should_skip(path_info: Path, config, p_size: float, file_ext, is_dir=False):
    """Check whether the file/directory inside archive files should be skipped based on various filters"""

    if (config.arc_include and not any(path_info.is_relative_to(inc) for inc in config.arc_include)) \
            or (config.arc_exclude and any(path_info.is_relative_to(exc) for exc in config.arc_exclude)) \
            or (config.arc_ext and file_ext not in config.arc_ext) \
            or (config.arc_exc_ext and file_ext in config.arc_exc_ext) \
            or (config.arc_size and (is_dir or not any(
                minimum <= p_size <= maximum
                for minimum, maximum in config.arc_size
            ))):
        return True

    if config.re_include:
        return not config.re_include.search(str(path_info))
    if config.re_exclude:
        return config.re_exclude.search(str(path_info)) is not None

    return False


def extract_names_from_archive(file_path: Path, config, depth: int = -1,
                               file_bytes: bytes | None = None, parent_label: list[str] | None = None):
    """
    Recursively extract files and directories name from archive files.
    Supports nested archives like a.zip::b.7z::c.txt.

    Parameters:
        file_path (Path): the archive file path
        depth (int): the depth value that is returned recursively
        file_bytes (bytes | None): optional byte data if already read (for recursion)
        parent_label (list): list for nested archive tracking like ["a.zip", "b_folder\\b.7z", "file.txt"]

    Yields:
        tuple[list, Path, bool]: parent label, file or directory name, is directory
    """

    file_ext = get_path_suffix(file_path)
    label_prefix = [*parent_label, str(file_path)] if parent_label is not None else []
    new_depth = depth + 1

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
                    is_dir = info.is_dir()

                    if not archive_should_skip(
                            name,
                            config,
                            get_archive_path_size(info, file_ext),
                            new_path_ext,
                            is_dir
                    ):
                        if any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                            yield label_prefix, name, is_dir

                        # Check if this is a nested archive
                        if new_path_ext in ARCHIVE_EXTS[:-3] and any(new_depth < d[1] for d in config.arc_depth):
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
                    is_dir = info.is_directory

                    if not archive_should_skip(
                            name,
                            config,
                            get_archive_path_size(info, '7z'),
                            new_path_ext,
                            is_dir
                    ):
                        if any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                            yield label_prefix, name, is_dir

                        if new_path_ext in ARCHIVE_EXTS[:-3] and any(new_depth < d[1] for d in config.arc_depth):
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
                    is_dir = member.isdir()

                    if not archive_should_skip(
                            name,
                            config,
                            get_archive_path_size(member, file_ext),
                            new_path_ext,
                            is_dir
                    ):
                        if any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                            yield label_prefix, name, is_dir

                        if new_path_ext in ARCHIVE_EXTS[:-3] and any(new_depth < d[1] for d in config.arc_depth):
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
    except (zipfile.BadZipFile, rarfile.Error, tarfile.ReadError, OSError):
        return  # silently skip invalid or unreadable archives


def extract_text_from_archive(file_path: Path, config, depth: int = -1,
                              file_bytes: bytes | None = None, parent_label: list[str] | None = None):
    """
    Recursively extract (path_label, text_content) from any archive file.
    Supports nested archives like a.zip::b.7z::c.txt.

    Parameters:
        file_path (Path): the archive file path
        depth (int): the depth value that is returned recursively
        file_bytes (bytes | None): optional byte data if already read (for recursion)
        parent_label (list): list for nested archive tracking like ["a.zip", "b_folder\\b.7z", "file.txt"]

    Yields:
        (list, str): list of virtual path, content text
    """

    file_ext = get_path_suffix(file_path)
    label_prefix = [*parent_label, str(file_path)] if parent_label is not None else []
    new_depth = depth + 1

    try:
        # Decide the stream source: from disk or memory
        file_stream = io.BytesIO(file_bytes) if file_bytes is not None else open(file_path, 'rb')

        # Handle ZIP and RAR archives
        if file_ext in ('zip', 'rar'):
            opener = {'zip': zipfile.ZipFile, 'rar': rarfile.RarFile}[file_ext]
            with opener(file_stream) as f:
                for info in f.infolist():
                    if info.is_dir():
                        continue
                    
                    file_name = Path(info.filename)
                    new_path_ext = get_path_suffix(file_name)
                    
                    if archive_should_skip(
                        file_name,
                        config,
                        get_archive_path_size(info, file_ext),
                        new_path_ext
                    ):
                        continue

                    with f.open(info) as entry:
                        head = entry.read(8192)

                        if is_binary(head) and new_path_ext not in ARCHIVE_EXTS:
                            continue

                        # 8 KiB has already been consumed from stream. If we use entry.read(), we will lose that 8 KiB
                        data = head + entry.read()

                    # Check if this is a nested archive
                    if new_path_ext in ARCHIVE_EXTS:
                        if any(new_depth < d[1] for d in config.arc_depth):
                            yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    elif any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                        yield [*label_prefix, str(file_name)], data
        # Handle 7Z archives
        elif file_ext == '7z':
            with py7zr.SevenZipFile(file_stream, mode='r') as archive:
                for info in archive.list():
                    if info.is_directory:
                        continue
                    
                    file_data = archive.read([info.filename]).get(info.filename)
                    if file_data is None:
                        continue

                    file_name = Path(info.filename)
                    new_path_ext = get_path_suffix(file_name)
                    
                    if archive_should_skip(
                        file_name,
                        config,
                        get_archive_path_size(info, '7z'),
                        new_path_ext
                    ):
                        continue
                    
                    head = file_data.read(8192)
                    if is_binary(head) and new_path_ext not in ARCHIVE_EXTS:
                        continue
                    
                    data = head + file_data.read()
                    if new_path_ext in ARCHIVE_EXTS:
                        if any(new_depth < d[1] for d in config.arc_depth):
                            yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    elif any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                        yield [*label_prefix, str(file_name)], data
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
                    if member.isdir():
                        continue
                    
                    f = tf.extractfile(member)
                    if f is None:
                        continue

                    file_name = Path(member.name)
                    new_path_ext = get_path_suffix(file_name)
                    
                    if archive_should_skip(
                        file_name,
                        config,
                        get_archive_path_size(member, file_ext),
                        new_path_ext
                    ):
                        continue
                    
                    head = f.read(8192)
                    if is_binary(head) and new_path_ext not in ARCHIVE_EXTS:
                        continue

                    data = head + f.read()
                    if new_path_ext in ARCHIVE_EXTS:
                        if any(new_depth < d[1] for d in config.arc_depth):
                            yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    elif any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                        yield [*label_prefix, str(file_name)], data
        # Handle single compressed files like .gz, .bz2, .xz
        elif file_ext in ARCHIVE_EXTS[-3:]:
            opener = {'gz': gzip.open, 'bz2': bz2.open, 'xz': lzma.open}[file_ext]
            with opener(file_stream, 'rb') as f:
                yield label_prefix, f.read()
    except (zipfile.BadZipFile, rarfile.Error, tarfile.ReadError, OSError, EOFError):
        return
