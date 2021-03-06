##############################################################################
# Copyright (c) 2013-2016, Lawrence Livermore National Security, LLC.
# Produced at the Lawrence Livermore National Laboratory.
#
# This file is part of Spack.
# Created by Todd Gamblin, tgamblin@llnl.gov, All rights reserved.
# LLNL-CODE-647188
#
# For details, see https://github.com/llnl/spack
# Please also see the NOTICE and LICENSE files for our notice and the LGPL.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License (as
# published by the Free Software Foundation) version 2.1, February 1999.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the IMPLIED WARRANTY OF
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the terms and
# conditions of the GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
##############################################################################
import os
import shutil

from llnl.util.filesystem import *
from llnl.util.lock import *

from spack.error import SpackError


class FileCache(object):
    """This class manages cached data in the filesystem.

    - Cache files are fetched and stored by unique keys.  Keys can be relative
      paths, so that thre can be some hierarchy in the cache.

    - The FileCache handles locking cache files for reading and writing, so
      client code need not manage locks for cache entries.

    """

    def __init__(self, root):
        """Create a file cache object.

        This will create the cache directory if it does not exist yet.

        """
        self.root = root.rstrip(os.path.sep)
        if not os.path.exists(self.root):
            mkdirp(self.root)

        self._locks = {}

    def destroy(self):
        """Remove all files under the cache root."""
        for f in os.listdir(self.root):
            path = join_path(self.root, f)
            if os.path.isdir(path):
                shutil.rmtree(path, True)
            else:
                os.remove(path)

    def cache_path(self, key):
        """Path to the file in the cache for a particular key."""
        return join_path(self.root, key)

    def _lock_path(self, key):
        """Path to the file in the cache for a particular key."""
        keyfile = os.path.basename(key)
        keydir = os.path.dirname(key)

        return join_path(self.root, keydir, '.' + keyfile + '.lock')

    def _get_lock(self, key):
        """Create a lock for a key, if necessary, and return a lock object."""
        if key not in self._locks:
            self._locks[key] = Lock(self._lock_path(key))
        return self._locks[key]

    def init_entry(self, key):
        """Ensure we can access a cache file. Create a lock for it if needed.

        Return whether the cache file exists yet or not.
        """
        cache_path = self.cache_path(key)

        exists = os.path.exists(cache_path)
        if exists:
            if not os.path.isfile(cache_path):
                raise CacheError("Cache file is not a file: %s" % cache_path)

            if not os.access(cache_path, os.R_OK | os.W_OK):
                raise CacheError("Cannot access cache file: %s" % cache_path)
        else:
            # if the file is hierarchical, make parent directories
            parent = os.path.dirname(cache_path)
            if parent.rstrip(os.path.sep) != self.root:
                mkdirp(parent)

            if not os.access(parent, os.R_OK | os.W_OK):
                raise CacheError("Cannot access cache directory: %s" % parent)

            # ensure lock is created for this key
            self._get_lock(key)
        return exists

    def read_transaction(self, key):
        """Get a read transaction on a file cache item.

        Returns a ReadTransaction context manager and opens the cache file for
        reading.  You can use it like this:

           with file_cache_object.read_transaction(key) as cache_file:
               cache_file.read()

        """
        return ReadTransaction(
            self._get_lock(key), lambda: open(self.cache_path(key)))

    def write_transaction(self, key):
        """Get a write transaction on a file cache item.

        Returns a WriteTransaction context manager that opens a temporary file
        for writing.  Once the context manager finishes, if nothing went wrong,
        moves the file into place on top of the old file atomically.

        """
        class WriteContextManager(object):

            def __enter__(cm):
                cm.orig_filename = self.cache_path(key)
                cm.orig_file = None
                if os.path.exists(cm.orig_filename):
                    cm.orig_file = open(cm.orig_filename, 'r')

                cm.tmp_filename = self.cache_path(key) + '.tmp'
                cm.tmp_file = open(cm.tmp_filename, 'w')

                return cm.orig_file, cm.tmp_file

            def __exit__(cm, type, value, traceback):
                if cm.orig_file:
                    cm.orig_file.close()
                cm.tmp_file.close()

                if value:
                    # remove tmp on exception & raise it
                    shutil.rmtree(cm.tmp_filename, True)

                else:
                    os.rename(cm.tmp_filename, cm.orig_filename)

        return WriteTransaction(self._get_lock(key), WriteContextManager)

    def mtime(self, key):
        """Return modification time of cache file, or 0 if it does not exist.

        Time is in units returned by os.stat in the mtime field, which is
        platform-dependent.

        """
        if not self.init_entry(key):
            return 0
        else:
            sinfo = os.stat(self.cache_path(key))
            return sinfo.st_mtime

    def remove(self, key):
        lock = self._get_lock(key)
        try:
            lock.acquire_write()
            os.unlink(self.cache_path(key))
        finally:
            lock.release_write()
        os.unlink(self._lock_path(key))


class CacheError(SpackError):
    pass
