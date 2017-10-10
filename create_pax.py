#!/usr/bin/env python3

import argparse
import datetime
import fcntl
import grp
import gzip
import hashlib
import io
import os
import os.path
import pathlib
import pwd
import socket
import stat
import sys
import tarfile
import threading


# Get information on what we're supposed to do!

argp = argparse.ArgumentParser(
    description='Make an archive of a directory',
    epilog='For help contact research-computing-support@stanford.edu',
)
argp.add_argument('-v', '--verbose',
    help='Print a line for every file processed.',
    action='store_true',
)
argp.add_argument('dir',
    help='The directory to archive.',
    type=str,
)
argp.add_argument('output',
    help='The path and name prefix to where files should be output.',
    type=str,
)
args = argp.parse_args()

# Check dir to make sure it's valid.

dir_path = pathlib.Path(args.dir)
if not dir_path.exists():
    raise OSError('Path %s does not exist!' % dir_path)
if not dir_path.is_dir():
    raise OSError('Path %s is not a directory!' % dir_path)
dir_path = dir_path.resolve()
print('Reading contents of', dir_path)

# Check output to make sure it's valid.

output_path = pathlib.Path(args.output)
output_dir = output_path.parent
output_prefix = output_path.name
if not output_dir.exists():
    raise OSError('Path %s does not exist!' % output_dir)
if not output_dir.is_dir():
    raise OSError('Path %s is not a directory!' % output_dir)
output_dir = output_dir.resolve()

if dir_path == output_dir:
    raise OSError('You are about to archive your output files!')

tar_path = output_dir.joinpath(output_prefix).with_suffix('.pax.gz')
if tar_path.exists():
    raise OSError('Path %s already exists!' % tar_path)
print('Writing to archive at', tar_path)

catalog_path = output_dir.joinpath(output_prefix).with_suffix('.txt')
if catalog_path.exists():
    raise OSError('Path %s already exists!' % catalog_path)
print('Writing to catalog at', catalog_path)

# Open our pax.gz and catalog files.

gzip_obj = gzip.open(
    filename=str(tar_path),
    mode='wb',
)

tar_obj = tarfile.TarFile(
    fileobj=gzip_obj,
    mode='w',
    format=tarfile.PAX_FORMAT,
)

catalog_obj = open(
    file=str(catalog_path),
    mode='w',
    encoding='utf-8',
)

# Set up our tar (pax) file writer.

def write_to_archive(tar_obj, item_path, stream):
    """Write an item to the tar file.

    :param pathlib.Path item_path: The Path object of the item.

    :param file stream: A stream, open for reading.

    :returns: None
    """

    # Get stat information from the path
    item_stat = item_path.stat()

    # Create a tar info object for our file.
    tar_info = tarfile.TarInfo(str(item_path.relative_to(dir_path)))
    tar_info.type = tarfile.REGTYPE
    tar_info.mode = item_stat.st_mode
    tar_info.uid = item_stat.st_uid
    tar_info.gid = item_stat.st_gid
    tar_info.mtime = item_stat.st_mtime
    tar_info.size = item_stat.st_size

    # Try resolving IDs to names.
    try:
        tar_info.uname = pwd.getpwuid(item_stat.st_uid).pw_name
    except KeyError:
        tar_info.uname = None
    try:
        tar_info.gname = grp.getgrgid(item_stat.st_gid).gr_name
    except KeyError:
        tar_info.gname = None

    # Actually add the file to the archive.
    tar_obj.addfile(tar_info, stream)

    # All done!
    return None

# Set up the code which writes to the catalog.

def write_catalog(catalog, item, checksum=None):
    # If there is no checksum, replace with all-zeroes.
    if checksum is None:
        checksum='0000000000000000000000000000000000000000'

    # Do one item_info, for us to extract individual fields.
    item_info = os.stat(str(item), follow_symlinks=False)

    # Regardless of item type, we'll always need some fields.
    mode = item_info.st_mode
    lastmod = item_info.st_mtime

    # If we have a directory, the size is N/A.
    if stat.S_ISDIR(mode):
        size = 'N/A'
    else:
        size = item_info.st_size

    # Output the catalog entry.
    print(stat.filemode(mode),
        checksum,
        size,
        datetime.datetime.fromtimestamp(lastmod).strftime('%Y-%m-%d %H:%M:%S'),
        item.name,
        file=catalog,
        sep="\t",
    )

    # All done!
    return None


# Start recursing through the directory!

dirs_to_examine = list()
dirs_to_examine.append(dir_path)
while len(dirs_to_examine) > 0:
    # Pull off the next directory in the queue, and add a header in the catalog.
    target_dir = dirs_to_examine.pop(0)
    if args.verbose is True:
        print('Processing directory', target_dir)
    print('', str(target_dir), file=catalog_obj)

    # Go through all of the items in the directory.
    for entry in target_dir.iterdir():

        # Get a path that is relative to our starting point.
        entry_relative_path = entry.relative_to(dir_path)

        # Symlinks are added immediately.
        # NOTE: We _must_ do this before any other checks, because we don't
        # want to accidentally end up archiving symlinked directories!
        if entry.is_symlink() is True:
            if args.verbose is True:
                print('', entry, '[symlink]')
            write_catalog(catalog_obj, entry)
            tar_obj.add(
                str(entry),
                arcname=str(entry_relative_path),
                recursive=False,
            )

        # For subdirectories, add a catalog item now, but queue up the
        # directory, so it can be processed later.
        elif entry.is_dir() is True:
            if args.verbose is True:
                print('', entry.name, '[directory; queued]')
            write_catalog(catalog_obj, entry)
            tar_obj.add(
                str(entry),
                arcname=str(entry_relative_path),
                recursive=False,
            )
            dirs_to_examine.append(entry)

        # Files use our threading code to hash and add in one go.
        elif entry.is_file() is True:
            if args.verbose is True:
                print('', entry.name)

            # Open the file for reading, along with a buffer and a hash.
            # We use a pipe as a buffer, since tar is in a separate thread.
            entry_obj = open(
                file=str(entry),
                mode='rb',
            )
            buffer_fd_tuple = os.pipe() # (writer_fd, reader_fd)
            buffer_out_obj = os.fdopen(buffer_fd_tuple[0], 'rb')
            buffer_in_obj = os.fdopen(buffer_fd_tuple[1], 'wb')
            hash_obj = hashlib.sha1()

            # Start our tar thread.
            tar_thread = threading.Thread(
                target=write_to_archive,
                name='tar %s' % str(entry),
                args=(
                    tar_obj,
                    entry,
                    buffer_out_obj,
                ),
                daemon=True,
            )
            tar_thread.start()

            # Start our read loop.  We read in 4k blocks (to match disk blocks).
            # For each block read, we add it into the hash, then send it off
            # for archiving.
            # NOTE: If we close the thread now, then TarFile will throw an
            # exception.  So, we flush after every write, and we close once
            # TarFile is done with its work.
            block = entry_obj.read(4096)
            while len(block) > 0:
                hash_obj.update(block)
                buffer_in_obj.write(block)
                buffer_in_obj.flush()
                block = entry_obj.read(4096)

            # Wait until our thread is done, then close the pipe.
            tar_thread.join()
            buffer_out_obj.close()
            buffer_in_obj.close()

            # Update the catalog.
            write_catalog(catalog_obj, entry, hash_obj.hexdigest())

            # Done processing the file!

        # Other things (like device files) are skipped.
        else:
            print(' Skipping non-file', entry)

    # Done processing entries!

# Close our files and exit!
print('Done!')
tar_obj.close()
gzip_obj.close()
catalog_obj.close()
sys.exit(0)
