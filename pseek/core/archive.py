import bz2
import gzip
import io
import lzma
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path

import py7zr
import rarfile

from ..structs import SysPath
from ..utils import is_binary

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


def get_mod_or_acc_time(info, file_type: str, sort_type: str,
                        requested_type: str = 'modified') -> int | None:
    if sort_type != requested_type:
        return None

    if file_type == 'zip':
        if requested_type == 'modified':
            mtime = datetime(*info.date_time).timestamp()
            time_ns = round(mtime * 1_000_000_000)
        else:
            time_ns = None
    elif file_type == 'rar':
        if requested_type == 'modified':
            time_ns = (
                round(info.mtime.timestamp() * 1_000_000_000)
                if info.mtime is not None else None
            )
        else:
            time_ns = (
                round(info.atime.timestamp() * 1_000_000_000)
                if info.atime is not None else None
            )
    elif file_type == '7z':
        properties = info.file_properties()

        if requested_type == 'modified':
            timestamp = properties.get('lastwritetime')
        else:
            timestamp = properties.get('lastaccesstime')

        if timestamp is None:
            return None

        time_ns = round(timestamp.totimestamp() * 1_000_000_000)
    elif file_type in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
        if requested_type == 'modified':
            time_ns = round(info.mtime * 1_000_000_000)
        else:
            atime_value = info.pax_headers.get('atime')
            time_ns = (
                round(float(atime_value) * 1_000_000_000)
                if atime_value is not None else None
            )

    return time_ns


def archive_should_skip(path_info: SysPath, config):
    """Check whether the file/directory inside archive files should be skipped based on various filters"""

    return (config.arc_include and not any(path_info.path.is_relative_to(inc) for inc in config.arc_include)) \
            or (config.arc_exclude and any(path_info.path.is_relative_to(exc) for exc in config.arc_exclude)) \
            or (config.arc_ext and path_info.suffix not in config.arc_ext) \
            or (config.arc_exc_ext and path_info.suffix in config.arc_exc_ext) \
            or (config.arc_size and (path_info.is_dir or not any(
                minimum <= path_info.size <= maximum
                for minimum, maximum in config.arc_size
            ))) or (config.re_include and not config.re_include.search(path_info.string)) \
        or (config.re_exclude and config.re_exclude.search(path_info.string) is not None)


def extract_names_from_archive(file_path: SysPath, config, depth: int = -1,
                               file_bytes: bytes | None = None, parent_label: list[str] | None = None):
    """
    Recursively extract files and directories name from archive files.
    Supports nested archives like a.zip::b.7z::c.txt.

    Parameters:
        file_path (SysPath): the archive file path
        depth (int): the depth value that is returned recursively
        file_bytes (bytes | None): optional byte data if already read (for recursion)
        parent_label (list): list for nested archive tracking like ["a.zip", "b_folder\\b.7z", "file.txt"]

    Yields:
        tuple[list, SysPath]: parent label, file or directory data
    """

    label_prefix = [*parent_label, file_path.string] if parent_label is not None else []
    new_depth = depth + 1

    try:
        # Decide the stream source: from disk or memory
        file_stream = io.BytesIO(file_bytes) if file_bytes is not None else open(file_path.path, 'rb')

        # Handle ZIP and RAR archives
        if file_path.suffix in ('zip', 'rar'):
            opener = {'zip': zipfile.ZipFile, 'rar': rarfile.RarFile}[file_path.suffix]
            with opener(file_stream) as f:
                for info in f.infolist():
                    is_dir = info.is_dir()
                    name = SysPath(
                        path=Path(info.filename),
                        is_file=not is_dir,
                        is_dir=is_dir,
                        psize=get_archive_path_size(info, file_path.suffix),
                        mtime_ns=get_mod_or_acc_time(info, file_path.suffix, config.sortby),
                        atime_ns=get_mod_or_acc_time(
                            info,
                            file_path.suffix,
                            config.sortby,
                            'accessed'
                        ),
                        depth=(
                            (file_path.depth, new_depth)
                            if not isinstance(file_path.depth, tuple)
                            else (file_path.depth[0], new_depth)
                        )
                    )

                    if not archive_should_skip(name, config):
                        if any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                            yield label_prefix, name

                        # Check if this is a nested archive
                        if name.suffix in ARCHIVE_EXTS[:-3] and any(new_depth < d[1] for d in config.arc_depth):
                            yield from extract_names_from_archive(
                                name,
                                config,
                                new_depth,
                                f.read(info),
                                label_prefix
                            )
        # Handle 7Z archives
        elif file_path.suffix == '7z':
            with py7zr.SevenZipFile(file_stream, mode='r') as z:
                for info in z.files:
                    is_dir = info.is_directory
                    name = SysPath(
                        path=Path(info.filename),
                        is_file=not is_dir,
                        is_dir=is_dir,
                        psize=get_archive_path_size(info, '7z'),
                        mtime_ns=get_mod_or_acc_time(info, '7z', config.sortby),
                        atime_ns=get_mod_or_acc_time(
                            info,
                            '7z',
                            config.sortby,
                            'accessed'
                        ),
                        depth=(
                            (file_path.depth, new_depth)
                            if not isinstance(file_path.depth, tuple)
                            else (file_path.depth[0], new_depth)
                        )
                    )

                    if not archive_should_skip(name, config):
                        if any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                            yield label_prefix, name

                        if name.suffix in ARCHIVE_EXTS[:-3] and any(
                            new_depth < d[1] for d in config.arc_depth
                        ):
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
        elif file_path.suffix in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
            # Specify the mode based on the file ext to open it
            mode = {
                'tar': 'r',
                'tar.gz': 'r:gz',
                'tar.bz2': 'r:bz2',
                'tar.xz': 'r:xz'
            }[file_path.suffix]

            with tarfile.open(fileobj=file_stream, mode=mode) as tf:
                for member in tf.getmembers():
                    is_dir = member.isdir()
                    name = SysPath(
                        path=Path(member.name),
                        is_file=not is_dir,
                        is_dir=is_dir,
                        psize=get_archive_path_size(member, file_path.suffix),
                        mtime_ns=get_mod_or_acc_time(member, file_path.suffix, config.sortby),
                        atime_ns=get_mod_or_acc_time(
                            member,
                            file_path.suffix,
                            config.sortby,
                            'accessed'
                        ),
                        depth=(
                            (file_path.depth, new_depth)
                            if not isinstance(file_path.depth, tuple)
                            else (file_path.depth[0], new_depth)
                        )
                    )

                    if not archive_should_skip(name, config):
                        if any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                            yield label_prefix, name

                        if name.suffix in ARCHIVE_EXTS[:-3] and any(new_depth < d[1] for d in config.arc_depth):
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


def extract_text_from_archive(file_path: SysPath, config, depth: int = -1,
                              file_bytes: bytes | None = None, parent_label: list[str] | None = None):
    """
    Recursively extract (path_label, text_content) from any archive file.
    Supports nested archives like a.zip::b.7z::c.txt.

    Parameters:
        file_path (SysPath): the archive file path
        depth (int): the depth value that is returned recursively
        file_bytes (bytes | None): optional byte data if already read (for recursion)
        parent_label (list): list for nested archive tracking like ["a.zip", "b_folder\\b.7z", "file.txt"]

    Yields:
        (list, str): list of virtual path, content text
    """

    label_prefix = [*parent_label, file_path.string] if parent_label is not None else []
    new_depth = depth + 1

    try:
        # Decide the stream source: from disk or memory
        file_stream = io.BytesIO(file_bytes) if file_bytes is not None else open(file_path.path, 'rb')

        # Handle ZIP and RAR archives
        if file_path.suffix in ('zip', 'rar'):
            opener = {'zip': zipfile.ZipFile, 'rar': rarfile.RarFile}[file_path.suffix]
            with opener(file_stream) as f:
                for info in f.infolist():
                    if info.is_dir():
                        continue

                    file_name = SysPath(
                        path=Path(info.filename),
                        is_file=True,
                        is_dir=False,
                        psize=get_archive_path_size(info, file_path.suffix),
                        mtime_ns=get_mod_or_acc_time(info, file_path.suffix, config.sortby),
                        atime_ns=get_mod_or_acc_time(
                            info,
                            file_path.suffix,
                            config.sortby,
                            'accessed'
                        ),
                        depth=(
                            (file_path.depth, new_depth)
                            if not isinstance(file_path.depth, tuple)
                            else (file_path.depth[0], new_depth)
                        )
                    )

                    if archive_should_skip(file_name, config):
                        continue

                    with f.open(info) as entry:
                        head = entry.read(8192)

                        if is_binary(head) and file_name.suffix not in ARCHIVE_EXTS:
                            continue

                        # 8 KiB has already been consumed from stream. If we use entry.read(), we will lose that 8 KiB
                        data = head + entry.read()

                    # Check if this is a nested archive
                    if file_name.suffix in ARCHIVE_EXTS:
                        if any(new_depth < d[1] for d in config.arc_depth):
                            yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    elif any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                        yield [*label_prefix, file_name], data
        # Handle 7Z archives
        elif file_path.suffix == '7z':
            with py7zr.SevenZipFile(file_stream, mode='r') as z:
                for info in z.files:
                    if info.is_directory:
                        continue

                    file_name = SysPath(
                        path=Path(info.filename),
                        is_file=True,
                        is_dir=False,
                        psize=get_archive_path_size(info, '7z'),
                        mtime_ns=get_mod_or_acc_time(info, '7z', config.sortby),
                        atime_ns=get_mod_or_acc_time(
                            info,
                            '7z',
                            config.sortby,
                            'accessed'
                        ),
                        depth=(
                            (file_path.depth, new_depth)
                            if not isinstance(file_path.depth, tuple)
                            else (file_path.depth[0], new_depth)
                        )
                    )

                    if archive_should_skip(file_name, config):
                        continue

                    file_data = z.read([info.filename]).get(info.filename)
                    if file_data is None:
                        continue

                    head = file_data.read(8192)
                    if is_binary(head) and file_name.suffix not in ARCHIVE_EXTS:
                        continue
                    
                    data = head + file_data.read()
                    if file_name.suffix in ARCHIVE_EXTS:
                        if any(new_depth < d[1] for d in config.arc_depth):
                            yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    elif any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                        yield [*label_prefix, file_name], data
        # Handle TAR and compressed TAR formats
        elif file_path.suffix in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
            mode = {
                'tar': 'r',
                'tar.gz': 'r:gz',
                'tar.bz2': 'r:bz2',
                'tar.xz': 'r:xz'
            }[file_path.suffix]

            with tarfile.open(fileobj=file_stream, mode=mode) as tf:
                for member in tf.getmembers():
                    if member.isdir():
                        continue
                    
                    f = tf.extractfile(member)
                    if f is None:
                        continue

                    file_name = SysPath(
                        path=Path(member.name),
                        is_file=True,
                        is_dir=False,
                        psize=get_archive_path_size(member, file_path.suffix),
                        mtime_ns=get_mod_or_acc_time(member, file_path.suffix, config.sortby),
                        atime_ns=get_mod_or_acc_time(
                            member,
                            file_path.suffix,
                            config.sortby,
                            'accessed'
                        ),
                        depth=(
                            (file_path.depth, new_depth)
                            if not isinstance(file_path.depth, tuple)
                            else (file_path.depth[0], new_depth)
                        )
                    )

                    if archive_should_skip(file_name, config):
                        continue
                    
                    head = f.read(8192)
                    if is_binary(head) and file_name.suffix not in ARCHIVE_EXTS:
                        continue

                    data = head + f.read()
                    if file_name.suffix in ARCHIVE_EXTS:
                        if any(new_depth < d[1] for d in config.arc_depth):
                            yield from extract_text_from_archive(file_name, config, new_depth, data, label_prefix)
                    elif any(mi <= new_depth <= ma for mi, ma in config.arc_depth):
                        yield [*label_prefix, file_name], data
        # Handle single compressed files like .gz, .bz2, .xz
        elif file_path.suffix in ARCHIVE_EXTS[-3:]:
            opener = {'gz': gzip.open, 'bz2': bz2.open, 'xz': lzma.open}[file_path.suffix]
            with opener(file_stream, 'rb') as f:
                if label_prefix:
                    label_prefix = [*label_prefix[:-1], file_path]
                yield label_prefix, f.read()
    except (zipfile.BadZipFile, rarfile.Error, tarfile.ReadError, OSError, EOFError):
        return
