# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2018 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, 51 Franklin Street, Fifth Floor, Boston, MA 02110-1335, USA.
#
# Authors:
#     Valerio Cosentino <valcos@bitergia.com>
#

from glob import glob
import io
import importlib
import logging
import os
import pkgutil
import shutil
import tarfile

from grimoirelab_toolkit.datetime import datetime_utcnow
from grimoirelab_toolkit.introspect import find_signature_parameters
from perceval.backends.core.git import (Git,
                                        GitRepository,
                                        GitCommand)
from perceval.backend import (uuid,
                              BackendCommandArgumentParser)
from perceval.errors import BaseError, RepositoryError
from perceval.utils import DEFAULT_DATETIME, DEFAULT_LAST_DATETIME

from ._version import __version__

CATEGORY_GRAAL = 'graal'
DEFAULT_WORKTREE_PATH = '/tmp/worktrees/'

logger = logging.getLogger(__name__)


class GraalError(BaseError):
    """Generic error for graal backends"""

    message = "%(cause)s"


class Graal(Git):
    """Generic Repository AnALyzer backend.

    This class inherits from Git backend, thus it fetches the commits
    from a local Git repository and enables to add the result of
    the analysis within the `analysis` attribute of the Perceval
    item returned. To initialize this class, you have to provide
    the local path of a Git repository (URI), a value for
    `git_path`, where the repository will be mirrored, and the path where
    a working tree will be created. The working tree is added to the
    mirror and removed after the analysis is over.

    For each target commit (by default all of them), a checkout version
    of the repository is created at `worktreepath` to ease the analysis.
    Note that you can customize the filter to select commits, by
    redefining the method `_filter_commit(self, commit)`.
    Furthermore, you can plug your analysis by redefining the
    method `_analyze(self, commit)` as well as tweak
    the item generated by redefining the method `_post(commit)`.

    :param uri: URI of the Git repository
    :param git_path: path to where is/to clone the repository
    :param worktreepath: the directory where to store the working tree
    :param entrypoint: the entrypoint of the analysis
    :param in_paths: the target paths of the analysis
    :param out_paths: the paths to be excluded from the analysis
    :param details: if enable, it returns fine-grained results
    :param tag: label used to mark the data
    :param archive: archive to store/retrieve items

    :raises RepositoryError: raised when there was an error cloning or
        updating the repository.
    """
    version = '0.2.1'

    CATEGORIES = [CATEGORY_GRAAL]

    def __init__(self, uri, gitpath, worktreepath=DEFAULT_WORKTREE_PATH,
                 entrypoint=None, in_paths=None, out_paths=None, details=False,
                 tag=None, archive=None):
        super().__init__(uri, gitpath, tag=tag, archive=archive)
        self.uri = uri
        self.gitpath = gitpath

        self.entrypoint = entrypoint
        self.in_paths = in_paths
        self.out_paths = out_paths
        self.details = details

        if not GraalRepository.exists(worktreepath):
            os.mkdir(worktreepath)

        self.worktreepath = os.path.join(worktreepath, os.path.split(self.gitpath)[1])
        self.graalRepo = None

    def fetch(self, category=CATEGORY_GRAAL,
              from_date=DEFAULT_DATETIME, to_date=DEFAULT_LAST_DATETIME,
              branches=None, latest_items=False):
        """Fetch commits and supports the inclusion of code
        analysis information.

        The method retrieves from a Git repository a list of
        commits. Commits are returned in the same order they were
        obtained.

        When `from_date` parameter is given it returns items commited
        since the given date.

        The list of `branches` is a list of strings, with the names of
        the branches to fetch. If the list of branches is empty, no
        commit is fetched. If the list of branches is None, all commits
        for all branches will be fetched.

        The parameter `latest_items` returns only those commits which
        are new since the last time this method was called.

        Take into account that `from_date` and `branches` are ignored
        when the commits are fetched from a Git log file or when
        `latest_items` flag is set.

        The class raises a `RepositoryError` exception when an error
        occurs accessing the repository.

        :param category: the category of items to fetch
        :param from_date: obtain commits newer than a specific date
            (inclusive)
        :param to_date: obtain commits older than a specific date
        :param branches: names of branches to fetch from (default: None)
        :param latest_items: sync with the repository to fetch only the
            newest commits

        :returns: a generator of commits
        """
        items = super().fetch(category=category,
                              from_date=from_date, to_date=to_date,
                              branches=branches, latest_items=latest_items)

        return items

    def fetch_items(self, category, **kwargs):
        """Fetch the commits and adds analysis information

        :param category: the category of items to fetch
        :param kwargs: backend arguments

        :returns: a generator of items
        """
        icommits = 0

        self.graalRepo = self.__create_graal_repository()

        commits = super().fetch_items(category, **kwargs)
        for commit in commits:
            try:
                if self._filter_commit(commit):
                    continue

                self.graalRepo.checkout(commit['commit'])
                commit['analysis'] = self._analyze(commit)

                commit = self._post(commit)
                yield commit
                icommits += 1
            except Exception as e:
                logger.error("Analysis failed at %s" % commit['commit'])
                raise e

        self.graalRepo.prune()

        logger.info("Fetch process completed: %s commits inspected",
                    icommits)

    def metadata(self, item):
        """Add metadata to an item.

        It adds metadata to a given item such as how and
        when it was fetched. The contents from the original item will
        be stored under the 'data' keyword.

        :param item: an item fetched by a backend
        """
        item = {
            'backend_name': self.__class__.__name__,
            'backend_version': self.version,
            'graal_version': __version__,
            'timestamp': datetime_utcnow().timestamp(),
            'origin': self.origin,
            'uuid': uuid(self.origin, self.metadata_id(item)),
            'updated_on': self.metadata_updated_on(item),
            'category': self.metadata_category(item),
            'tag': self.tag,
            'data': item,
        }

        return item

    @staticmethod
    def metadata_category(item):
        """Extracts the category from a Graal item.

        This backend only generates one type of item which is
        'commit'.
        """
        return CATEGORY_GRAAL

    def _filter_commit(self, commit):
        """Filter a commit according to its data (e.g., author, sha, etc.)

        :param commit: a Perceval commit item

        :returns: a boolean value
        """
        return False

    def _analyze(self, commit):
        """Analyze a commit and the corresponding
        checkout version of the repository

        :param commit: a Perceval commit item
        """
        return {}

    def _post(self, commit):
        """Perform operation (e.g., removing attributes) on the Graal item obtained

        :param commit: a Graal commit item
        """
        return commit

    def __create_graal_repository(self):
        if not GraalRepository.exists(self.gitpath):
            repo = GraalRepository.clone(self.uri, self.gitpath)
        elif os.path.isdir(self.gitpath):
            repo = GraalRepository(self.uri, self.gitpath)

        if GraalRepository.exists(self.worktreepath):
            shutil.rmtree(self.worktreepath)

        repo.worktree(self.worktreepath)
        return repo


class GraalRepository(GitRepository):
    """Manage a Graal repository.

    This class extends the GitRepository class. Thus, it provides some
    additional commands such as `worktree`, `create_tar` or `untar`.

    :param uri: URI of the repository
    :param dirpath: local directory where the repository is stored
    """

    def __init__(self, uri, dirpath):
        super().__init__(uri, dirpath)
        self.worktreepath = None

    def worktree(self, worktreepath, branch=None):
        """Create a working tree of the cloned repository with the active branch
        set to `branch`

        :param worktreepath: the path where the working tree will be located
        :param branch: the name of the branch. If None, the branch is set to `master`
        """
        self.worktreepath = worktreepath

        if not branch:
            branch = 'master'

        cmd_worktree = ['git', 'worktree', 'add', self.worktreepath, branch]

        try:
            self._exec(cmd_worktree, cwd=self.dirpath, env=self.gitenv)
            logger.info("Git worktree %s created!" % self.worktreepath)
            return
        except Exception:
            pass

        try:
            self.prune()
            self.worktree(worktreepath, branch)
        except RepositoryError:
            cause = "Impossible to create the worktree %s" % (self.worktreepath)
            raise RepositoryError(cause=cause)

    def prune(self):
        """Delete a working tree from disk

        :param worktreepath: directory where the working tree is located
        """
        GraalRepository.delete(self.worktreepath)
        cmd_worktree = ['git', 'worktree', 'prune']
        try:
            self._exec(cmd_worktree, cwd=self.dirpath, env=self.gitenv)
            logger.info("Git worktree %s deleted!" % self.worktreepath)
        except Exception:
            cause = "Impossible to delete the worktree %s" % (self.worktreepath)
            raise RepositoryError(cause=cause)

    def checkout(self, hash):
        """Checkout a Git repository at a given commit

        :param hash: the hash of a commit
        """
        cmd_checkout = ['git', 'checkout', hash]
        try:
            self._exec(cmd_checkout, cwd=self.worktreepath, env=self.gitenv)
            logger.info("Git repository %s checked out!" % self.dirpath)
        except Exception:
            cause = "Impossible to checkout the worktree %s at %s" % (self.worktreepath, hash)
            raise RepositoryError(cause=cause)

    def archive(self, hash):
        """Create an archive using the git archive command

        :param hash: the hash of a commit

        :returns: a BytesIO object
        """
        cmd_archive = ['git', 'archive', '--format=tar', hash]

        try:
            outs = self._exec(cmd_archive, cwd=self.dirpath, env=self.gitenv)
            file_obj = io.BytesIO(outs)
        except OSError:
            logger.error("Archive for %s could not be created", hash)
            file_obj = None

        return file_obj

    @staticmethod
    def tar_obj(file_obj):
        """Create a tar object from a BytesIO object.

        :param file_obj: a BytesIO object

        :returns: a tar object
        """
        try:
            tar_obj = tarfile.open(fileobj=file_obj)
        except tarfile.ReadError:
            # this may happen because file_like_object is empty
            logger.warning("Tar object was not created")
            return None

        return tar_obj

    @staticmethod
    def filter_tar(tar_obj, paths):
        """Create a tar object from a BytesIO object.

        :param tar_obj: a BytesIO object
        :param paths: a list of paths to be included in the tar
        """
        selected_members = [member for member in tar_obj.getmembers() if member.name in paths]
        tar_obj.members = selected_members

        if not tar_obj.members:
            return None

        return tar_obj

    @staticmethod
    def tar(tar_obj, dest):
        """Save a tar object to the `dest` path

        :param tar_obj: a tar object
        :param dest: a destination path
        """
        tar = tarfile.open(dest, "w:gz")
        for member in tar_obj.getmembers():
            tar.addfile(member)
        tar.close()

        logger.info("Tar file created at %s" % dest)

    @staticmethod
    def exists(dest):
        """Check that a dest path exists

        :param dest: a destination path
        """

        return os.path.exists(dest)

    @staticmethod
    def untar(tar_obj, dest):
        """Untar a tar obj to the `dest` directory

        :param tar_obj: a tar obj
        :param dest: a destination folder
        """
        if not GraalRepository.exists(dest):
            os.mkdir(dest)

        tar_obj.extractall(path=dest)
        logger.info("Tar object untarred at %s" % dest)

    @staticmethod
    def extension(file_path):
        """Get the extension of a file"""

        ext = file_path.split(".")[-1]
        return ext

    @staticmethod
    def files(dir_path):
        """List all files in a target dir

        :param dir_path: the path of the target directory
        """
        if not dir_path or not os.path.exists(dir_path):
            return []

        everything = glob(dir_path + '/**/*', recursive=True)
        onlyfiles = [f for f in everything if os.path.isfile(f)]
        return onlyfiles

    @staticmethod
    def delete(target_path):
        """Delete a a file or directory from disk

        :param target_path: the path of the target to be deleted
        """
        if not target_path or not os.path.exists(target_path):
            logger.warning("The path %s does not exist!" % target_path)
            return

        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)

        logger.info("%s deleted!" % target_path)


class GraalCommand(GitCommand):
    """Class to run GraalRepository backend from the command line."""

    BACKEND = Graal

    def _pre_init(self):
        """Initialize repositories directory path"""

        git_path = self.parsed_args.git_path
        setattr(self.parsed_args, 'gitpath', git_path)

    @staticmethod
    def setup_cmd_parser():
        """Returns the Graal argument parser."""

        parser = BackendCommandArgumentParser(from_date=True, to_date=True)

        # Optional arguments
        group = parser.parser.add_argument_group('Git arguments')
        group.add_argument('--branches', dest='branches',
                           nargs='+', type=str, default=None,
                           help="Fetch commits only from these branches")
        group.add_argument('--latest-items', dest='latest_items',
                           action='store_true',
                           help="Fetch latest commits added to the repository")
        group.add_argument('--worktree-path', dest='worktreepath',
                           default=DEFAULT_WORKTREE_PATH,
                           help="Path where to save the working tree")
        group.add_argument('--in-paths', dest='in_paths',
                           nargs='+', type=str, default=None,
                           help="Target paths of the analysis")
        group.add_argument('--out-paths', dest='out_paths',
                           nargs='+', type=str, default=None,
                           help="Paths to be excluded from the analysis")
        group.add_argument('--entrypoint', dest='entrypoint',
                           type=str, default=None,
                           help="Entrypoint of the analysis")
        group.add_argument('--details', dest='details',
                           action='store_true', default=False,
                           help="include details")

        # Required arguments
        parser.parser.add_argument('uri',
                                   help="URI of the Git log repository")
        parser.parser.add_argument('--git-path', dest='git_path',
                                   help="Path where the Git repository will be cloned")

        return parser


def fetch(backend_class, backend_args, category):
    """Fetch items using the given backend.

    Generator to get items using the given backend class.

    The parameters needed to initialize the `backend` class and
    get the items are given using `backend_args` dict parameter.

    :param backend_class: backend class to fetch items
    :param backend_args: dict of arguments needed to fetch the items
    :param category: category of the items to retrieve

    :returns: a generator of items
    """
    init_args = find_signature_parameters(backend_class.__init__,
                                          backend_args)
    init_args['archive'] = None

    backend = backend_class(**init_args)

    if category:
        backend_args['category'] = category

    fetch_args = find_signature_parameters(backend.fetch,
                                           backend_args)
    items = backend.fetch(**fetch_args)

    try:
        for item in items:
            yield item
    except Exception as e:
        raise e


def find_backends(top_package):
    """Find available backends.

    Look for the Perceval backends and commands under `top_package`
    and its sub-packages. When `top_package` defines a namespace,
    backends under that same namespace will be found too.

    :param top_package: package storing backends

    :returns: a tuple with two dicts: one with `Backend` classes and one
        with `BackendCommand` classes
    """
    candidates = pkgutil.walk_packages(top_package.__path__,
                                       prefix=top_package.__name__ + '.')

    modules = [name for _, name, is_pkg in candidates if not is_pkg]

    return _import_backends(modules)


def _import_backends(modules):
    for module in modules:
        importlib.import_module(module)

    bkls = _find_classes(Graal, modules)
    ckls = _find_classes(GraalCommand, modules)

    backends = {name: kls for name, kls in bkls}
    commands = {name: klass for name, klass in ckls}

    return backends, commands


def _find_classes(parent, modules):
    parents = parent.__subclasses__()

    while parents:
        kls = parents.pop()

        m = kls.__module__

        if m not in modules:
            continue

        name = m.split('.')[-1]
        parents.extend(kls.__subclasses__())

        yield name, kls
