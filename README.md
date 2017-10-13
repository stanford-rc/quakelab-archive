# quakelab-archive: A program to archive a directory tree

This program takes a directory tree, and creates a compressed archive of the
directory tree; along with a text file containing a human-readable, searchable
catalog of what was archived.

This program only has two requirements:

1. Python 3.4 or later, with threading enabled.

2. A POSIX-compliant OS (which includes Linux).

Point 1 is the reason I wrote this: I wanted it to be able to run in as many
places as possible, which meant using only functionality available in stock
Python.

Threading is used for performance, allowing a file's data to be passed through
checksumming, and then handed off for archiving.

# How to use

To use, run like this:

    python3 create_pax.py /path/to/archive /output/path

… or …

    ./create_pax.py /path/to/archive /output/path

In the above example, all files and directories within `/path/to/archive` would
be archived.  The archive would be written to `/output/path.pax.gz`, and the
catalog would be written to `/output/path.txt`.  `/path/to/archive` needs to be
a directory; we archive whole directory trees, not files!

> **NOTE:** Only items actually within `/path/to/archive` will be archived!
> If you have a symlink pointing outside of the directory tree, the symlink
> will be archived, but the item being pointed to would only be archived if the
> real item lives in the directory tree.

Within the archive, all of the items will have the `/path/to/archive` prefix
stripped from their path.  But, that information is retained in the catalog
(see below)!

# The Catalog

The catalog is a UTF-8-encoded text file, listing all of the items that can be
found in the archive.  Here is an example of what a catalog looks like:

    
     /b4_2/home/somebody
    -rw-rwx---      7682aeda3e660192ade888fd4d5ff1843dd75dd8        33      2011-09-12 13:22:06     .bash_logout
    -rw-rwx---      fe919c7cb7478d0e36a923dfc65895d8c90db426        176     2011-09-12 13:22:06     .bash_profile
    drwx------      0000000000000000000000000000000000000000        N/A     2015-01-09 11:44:22     .ssh
    lrwxrwxrwx      0000000000000000000000000000000000000000        18      2013-08-16 19:37:28     file.tgz -> file_7.3-26.tar.gz

The first line of the catalog is the absolute path of the directory.  Each
directory has a space at the start, and a blank line immediately before it.
That is there in case anyone wants to try parsing the catalog in the future.
Basically, if you have a blank line, and the next line starts with a space, you
have a new directory!

> **NOTE:** Absolute paths are _not_ stored in the archive.  Instead, all paths
> are relative to the path that was provided on the command-line.

The catalog includes directories, files, and symbolic links.  In the above
examples, the first two entries are files, the second a directory, and the
third a symlink.  All items start out with the UNIX-style permissions, shown
the same way as if you had run `ls -l` on a command line.

> **NOTE**: The archive also includes the owner & group of the item, though
> that information is not included in the catalog.

The second item for each entry is the entry's SHA-1 checksum.  Directories and
files do not have a checksum, so it is replaced with all zeroes.

The third item for each entry is the size of the item, in bytes.  Directories
do not have a size, so `N/A` is used instead.  For symlinks, the size of the
item is the number of characters in the target of the symlink.

The fourth item for each entry is its modification date.

> **NOTE**: Time zone information is not included in the catalog, but is
> accounted for in the archive.

The last item is the name.  If the item is a symlink, the name will be followed
by the target of the symlink.

> **NOTE**: The target of the symlink is _not_ modified.  If the symlink is a
> relative path, referring to an item in directory tree which is being
> archived, then the symlink should continue to work when the archive is
> expanded.  However, if the symlink is an absolute path, or is pointing to a
> location outside of the directory tree then the symlink will likely be broken
> when it is expanded.

# The Archive

The archive file is a pax file.  The pax format was defined in the POSIX.1-2001
standard, and is preferable for a number of reasons:

* There are no limitations on path length.

* Paths are UTF-8 encoded.

* You can attach additional metadata to archives, and to files, in the form of
  name-value pairs.

The archive is level-9 GZip-compressed.

Today, almost all `tar` implementations are able to understand the file format,
so expanding the archive is as simple as running…

    tar -xzf something.pax.gz
