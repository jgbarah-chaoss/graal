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

import logging
import os

from graal.graal import (Graal,
                         GraalRepository,
                         GraalCommand,
                         DEFAULT_WORKTREE_PATH)
from graal.backends.core.analyzers.cloc import Cloc
from graal.backends.core.analyzers.lizard import Lizard
from perceval.backend import BackendCommandArgumentParser
from perceval.utils import DEFAULT_DATETIME, DEFAULT_LAST_DATETIME

CATEGORY_COCOM = 'code_complexity'

logger = logging.getLogger(__name__)


class CoCom(Graal):
    """CoCom backend.

    This class extends the Graal backend. It gathers
    insights about code complexity, such as cyclomatic complexity,
    number of functions and lines of code of a several programming
    languages such as:
        C/C++ (works with C++14)
        Java
        C# (C Sharp)
        JavaScript
        Objective C
        Swift
        Python
        Ruby
        TTCN-3
        PHP
        Scala
        GDScript

    :param uri: URI of the Git repository
    :param gitpath: path to the repository or to the log file
    :param worktreepath: the directory where to store the working tree
    :param functions: if enabled, it returns complexity data about each single function found
    :param tag: label used to mark the data
    :param archive: archive to store/retrieve items

    :raises RepositoryError: raised when there was an error cloning or
        updating the repository.
    """
    version = '0.1.2'

    CATEGORIES = [CATEGORY_COCOM]

    def __init__(self, uri, git_path, worktreepath=DEFAULT_WORKTREE_PATH, functions=False,
                 tag=None, archive=None):
        super().__init__(uri, git_path, worktreepath, tag=tag, archive=archive)
        self.file_analyzer = FileAnalyzer(functions)

    def fetch(self, category=CATEGORY_COCOM, paths=None,
              from_date=DEFAULT_DATETIME, to_date=DEFAULT_LAST_DATETIME,
              branches=None, latest_items=False):
        """Fetch commits and add code complexity information."""

        items = super().fetch(category, paths=paths,
                              from_date=from_date, to_date=to_date,
                              branches=branches, latest_items=latest_items)

        return items

    @staticmethod
    def metadata_category(item):
        """Extracts the category from a Code item.

        This backend only generates one type of item which is
        'code_complexity'.
        """
        return CATEGORY_COCOM

    def _filter_commit(self, commit, ncommit, paths=None):
        """Filter a commit according to its data (e.g., author, sha, etc.)

        :param commit: a Perceval commit item
        :param ncommit: commit number (from the initial commit)
        :param paths: a list of paths to drive the filtering

        :returns: a boolean value
        """
        if not paths:
            return False

        for f in commit['files']:
            for p in paths:
                if f['file'].endswith(p):
                    return False

        return True

    def _analyze(self, commit, paths=None):
        """Analyse a commit and the corresponding
        checkout version of the repository

        :param commit: a Perceval commit item
        :param paths: a list of paths to narrow the analysis
        """
        files = GraalRepository.files(self.worktreepath)
        analysis = []

        for f in files:

            if paths:
                found = [p for p in paths if f.endswith(p)]
                if not found:
                    continue

            file_path = os.path.join(self.worktreepath, f)
            file_info = self.file_analyzer.analyze(file_path)
            file_info.update({'file_path': f})
            analysis.append(file_info)

        return analysis

    def _post(self, commit):
        """Remove attributes of the Graal item obtained

        :param commit: a Graal commit item
        """
        commit.pop('Author', None)
        commit.pop('Commit', None)
        commit.pop('files', None)
        commit.pop('parents', None)
        commit.pop('refs', None)
        return commit


class FileAnalyzer:
    """Class to analyse the content of files"""

    ALLOWED_EXTENSIONS = ['java', 'py', 'php', 'scala', 'js', 'rb', 'cs', 'cpp', 'c']
    FORBIDDEN_EXTENSIONS = ['tar', 'bz2', "gz", "lz", "apk", "tbz2",
                            "lzma", "tlz", "war", "xar", "zip", "zipx"]

    def __init__(self, functions=False):
        self.functions = functions
        self.cloc = Cloc()
        self.lizard = Lizard()

    def analyze(self, file_path):
        """Analyze the content of a file using CLOC and Lizard

        :param file_path: file path

        :returns a dict containing the results of the analysis, like the one below
        {
          'blanks': ..,
          'comments': ..,
          'loc': ..,
          'ccn': ..,
          'avg_ccn': ..,
          'avg_loc': ..,
          'avg_tokens': ..,
          'funs': ..,
          'tokens': ..,
          'funs_data': [..]
        }
        """
        kwargs = {'file_path': file_path}
        cloc_analysis = self.cloc.analyze(**kwargs)

        if GraalRepository.extension(file_path) not in self.ALLOWED_EXTENSIONS:
            return cloc_analysis

        kwargs['functions'] = self.functions
        lizard_analysis = self.lizard.analyze(**kwargs)
        # the LOC returned by CLOC is replaced by the one obtained with Lizard
        # for consistency purposes

        lizard_analysis['blanks'] = cloc_analysis['blanks']
        lizard_analysis['comments'] = cloc_analysis['comments']

        return lizard_analysis


class CoComCommand(GraalCommand):
    """Class to run CoCom backend from the command line."""

    BACKEND = CoCom

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
        group.add_argument('--paths', dest='paths',
                           nargs='+', type=str, default=None,
                           help="Paths to narrow the analysis")
        group.add_argument('--functions', dest='functions',
                           action='store_true', default=False,
                           help="get function details")

        # Required arguments
        parser.parser.add_argument('uri',
                                   help="URI of the Git log repository")
        parser.parser.add_argument('--git-path', dest='git_path',
                                   help="Path where the Git repository will be cloned")

        return parser