#!/usr/bin/env python3
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

import os
import shutil
import subprocess
import tempfile
import unittest.mock

from perceval.backend import BackendCommandArgumentParser
from perceval.utils import DEFAULT_DATETIME

from graal.analyzers.cloc import Cloc
from graal.analyzers.lizard import Lizard
from graal.codecomplexity import (DEFAULT_WORKTREE_PATH,
                                  CATEGORY_CODE_COMPLEXITY,
                                  CodeComplexity,
                                  FileAnalyzer,
                                  CodeComplexityCommand)
from tests.test_graal import TestCaseGraal
from tests.test_case_analyzer import (ANALYZER_TEST_FILE,
                                      TestCaseAnalyzer)


class TestCodeComplexityBackend(TestCaseGraal):
    """Graal backend tests"""

    @classmethod
    def setUpClass(cls):
        cls.tmp_path = tempfile.mkdtemp(prefix='codecomplexity_')
        cls.tmp_repo_path = os.path.join(cls.tmp_path, 'repos')
        os.mkdir(cls.tmp_repo_path)

        cls.git_path = os.path.join(cls.tmp_path, 'graaltest')
        cls.worktree_path = os.path.join(cls.tmp_path, 'codecomplexity_worktrees')

        data_path = os.path.dirname(os.path.abspath(__file__))
        data_path = os.path.join(data_path, 'data/graal')

        repo_name = 'graaltest'
        repo_path = cls.git_path

        fdout, _ = tempfile.mkstemp(dir=cls.tmp_path)

        zip_path = os.path.join(data_path, repo_name + '.zip')
        subprocess.check_call(['unzip', '-qq', zip_path, '-d', cls.tmp_repo_path])

        origin_path = os.path.join(cls.tmp_repo_path, repo_name)
        subprocess.check_call(['git', 'clone', '-q', '--bare', origin_path, repo_path],
                              stderr=fdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp_path)

    def test_initialization(self):
        """Test whether attributes are initializated"""

        cc = CodeComplexity('http://example.com', self.git_path, self.worktree_path, tag='test')
        self.assertEqual(cc.uri, 'http://example.com')
        self.assertEqual(cc.gitpath, self.git_path)
        self.assertEqual(cc.worktreepath, os.path.join(self.worktree_path, os.path.split(cc.gitpath)[1]))
        self.assertEqual(cc.origin, 'http://example.com')
        self.assertEqual(cc.tag, 'test')
        self.assertEqual(cc.file_analyzer.functions, False)

        cc = CodeComplexity('http://example.com', self.git_path, self.worktree_path, functions=True, tag='test')
        self.assertEqual(cc.uri, 'http://example.com')
        self.assertEqual(cc.gitpath, self.git_path)
        self.assertEqual(cc.worktreepath, os.path.join(self.worktree_path, os.path.split(cc.gitpath)[1]))
        self.assertEqual(cc.origin, 'http://example.com')
        self.assertEqual(cc.tag, 'test')
        self.assertEqual(cc.file_analyzer.functions, True)

        # When tag is empty or None it will be set to the value in uri
        cc = CodeComplexity('http://example.com', self.git_path, self.worktree_path)
        self.assertEqual(cc.origin, 'http://example.com')
        self.assertEqual(cc.tag, 'http://example.com')

        cc = CodeComplexity('http://example.com', self.git_path, self.worktree_path)
        self.assertEqual(cc.origin, 'http://example.com')
        self.assertEqual(cc.tag, 'http://example.com')

    def test_fetch(self):
        """Test whether commits are properly processed"""

        cc = CodeComplexity('http://example.com', self.git_path, self.worktree_path)
        commits = [commit for commit in cc.fetch(paths=['tests/client.py'])]

        self.assertEqual(len(commits), 5)
        self.assertFalse(os.path.exists(cc.worktreepath))

        for commit in commits:
            self.assertEqual(commit['backend_name'], 'CodeComplexity')
            self.assertEqual(commit['category'], CATEGORY_CODE_COMPLEXITY)
            self.assertEqual(commit['data']['analysis'][0]['file_path'],
                             os.path.join(cc.worktreepath, 'tests/client.py'))
            self.assertFalse('Author' in commit['data'])
            self.assertFalse('Commit' in commit['data'])
            self.assertFalse('files' in commit['data'])
            self.assertFalse('parents' in commit['data'])
            self.assertFalse('refs' in commit['data'])


class TestFileAnalyzer(TestCaseAnalyzer):
    """FileAnalyzer tests"""

    def test_init(self):
        """Test initialization"""

        file_analyzer = FileAnalyzer()

        self.assertIsInstance(file_analyzer, FileAnalyzer)
        self.assertIsInstance(file_analyzer.cloc, Cloc)
        self.assertIsInstance(file_analyzer.lizard, Lizard)
        self.assertFalse(file_analyzer.functions)

        file_analyzer = FileAnalyzer(functions=True)

        self.assertIsInstance(file_analyzer, FileAnalyzer)
        self.assertIsInstance(file_analyzer.cloc, Cloc)
        self.assertIsInstance(file_analyzer.lizard, Lizard)
        self.assertTrue(file_analyzer.functions)

    def test_analyze_no_functions(self):
        """Test whether the analyze method works"""

        file_path = os.path.join(self.tmp_data_path, ANALYZER_TEST_FILE)
        file_analyzer = FileAnalyzer()
        analysis = file_analyzer.analyze(file_path)

        self.assertNotIn('funs_data', analysis)
        self.assertIn('ccn', analysis)
        self.assertIn('avg_loc', analysis)
        self.assertIn('avg_tokens', analysis)
        self.assertIn('loc', analysis)
        self.assertIn('tokens', analysis)
        self.assertIn('blanks', analysis)
        self.assertIn('comments', analysis)

    def test_analyze_functions(self):
        """Test whether the analyze method returns functions information"""

        file_path = os.path.join(self.tmp_data_path, ANALYZER_TEST_FILE)
        file_analyzer = FileAnalyzer(functions=True)
        analysis = file_analyzer.analyze(file_path)

        self.assertIn('ccn', analysis)
        self.assertIn('avg_loc', analysis)
        self.assertIn('avg_tokens', analysis)
        self.assertIn('loc', analysis)
        self.assertIn('tokens', analysis)
        self.assertIn('blanks', analysis)
        self.assertIn('comments', analysis)
        self.assertIn('funs_data', analysis)

        for fd in analysis['funs_data']:
            self.assertIn('ccn', fd)
            self.assertIn('tokens', fd)
            self.assertIn('loc', fd)
            self.assertIn('lines', fd)
            self.assertIn('name', fd)
            self.assertIn('args', fd)
            self.assertIn('start', fd)
            self.assertIn('end', fd)


class TestCodeComplexityCommand(unittest.TestCase):
    """GraalCommand tests"""

    def test_backend_class(self):
        """Test if the backend class is Graal"""

        self.assertIs(CodeComplexityCommand.BACKEND, CodeComplexity)

    def test_setup_cmd_parser(self):
        """Test if it parser object is correctly initialized"""

        parser = CodeComplexityCommand.setup_cmd_parser()
        self.assertIsInstance(parser, BackendCommandArgumentParser)

        args = ['http://example.com/',
                '--git-path', '/tmp/gitpath',
                '--tag', 'test']

        parsed_args = parser.parse(*args)
        self.assertEqual(parsed_args.uri, 'http://example.com/')
        self.assertEqual(parsed_args.git_path, '/tmp/gitpath')
        self.assertEqual(parsed_args.tag, 'test')
        self.assertEqual(parsed_args.from_date, DEFAULT_DATETIME)
        self.assertEqual(parsed_args.to_date, None)
        self.assertEqual(parsed_args.branches, None)
        self.assertFalse(parsed_args.latest_items)
        self.assertEqual(parsed_args.worktreepath, DEFAULT_WORKTREE_PATH)
        self.assertEqual(parsed_args.paths, None)
        self.assertFalse(parsed_args.functions)

        args = ['http://example.com/',
                '--git-path', '/tmp/gitpath',
                '--tag', 'test',
                '--worktree-path', '/tmp/custom-worktrees/',
                '--paths', '*.py', '*.java',
                '--functions']

        parsed_args = parser.parse(*args)
        self.assertEqual(parsed_args.uri, 'http://example.com/')
        self.assertEqual(parsed_args.git_path, '/tmp/gitpath')
        self.assertEqual(parsed_args.tag, 'test')
        self.assertEqual(parsed_args.worktreepath, '/tmp/custom-worktrees/')
        self.assertEqual(parsed_args.paths, ['*.py', '*.java'])
        self.assertTrue(parsed_args.functions)


if __name__ == "__main__":
    unittest.main()