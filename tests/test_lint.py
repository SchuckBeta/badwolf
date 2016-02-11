# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals
import os

import mock
from unidiff import PatchSet

from badwolf.spec import Specification
from badwolf.runner import TestContext
from badwolf.lint.processor import LintProcessor


CURR_PATH = os.path.abspath(os.path.dirname(__file__))
FIXTURES_PATH = os.path.join(CURR_PATH, 'fixtures')


def test_no_linters_ignore(app):
    context = TestContext(
        'deepanalyzer/badwolf',
        'git@bitbucket.org:deepanalyzer/badwolf.git',
        None,
        'pullrequest',
        'message',
        {'commit': {'hash': '000000'}},
        {'commit': {'hash': '111111'}},
        pr_id=1
    )
    spec = Specification()
    lint = LintProcessor(context, spec, '/tmp')
    with mock.patch.object(lint, 'load_changes') as load_changes:
        lint.process()
        load_changes.assert_not_called()


def test_load_changes_failed_ignore(app, caplog):
    context = TestContext(
        'deepanalyzer/badwolf',
        'git@bitbucket.org:deepanalyzer/badwolf.git',
        None,
        'pullrequest',
        'message',
        {'commit': {'hash': '000000'}},
        {'commit': {'hash': '111111'}},
        pr_id=1
    )
    spec = Specification()
    spec.linters.append('flake8')
    lint = LintProcessor(context, spec, '/tmp')
    with mock.patch.object(lint, 'load_changes') as load_changes:
        load_changes.return_value = None
        lint.process()

        assert load_changes.called

    assert 'Load changes failed' in caplog.text()


def test_no_changed_files_ignore(app, caplog):
    diff = """diff --git a/removed_file b/removed_file
deleted file mode 100644
index 1f38447..0000000
--- a/removed_file
+++ /dev/null
@@ -1,3 +0,0 @@
-This content shouldn't be here.
-
-This file will be removed.
"""

    context = TestContext(
        'deepanalyzer/badwolf',
        'git@bitbucket.org:deepanalyzer/badwolf.git',
        None,
        'pullrequest',
        'message',
        {'commit': {'hash': '000000'}},
        {'commit': {'hash': '111111'}},
        pr_id=1
    )
    spec = Specification()
    spec.linters.append('flake8')
    lint = LintProcessor(context, spec, '/tmp')
    patch = PatchSet(diff.split('\n'))
    with mock.patch.object(lint, 'load_changes') as load_changes:
        load_changes.return_value = patch
        lint.process()

        assert load_changes.called

    assert 'No changed files found' in caplog.text()


def test_flake8_lint_a_py(app, caplog):
    diff = """diff --git a/a.py b/a.py
new file mode 100644
index 0000000..fdeea15
--- /dev/null
+++ b/a.py
@@ -0,0 +1,6 @@
+# -*- coding: utf-8 -*-
+from __future__ import absolute_import, unicode_literals
+
+
+def add(a, b):
+    return a+ b
"""

    context = TestContext(
        'deepanalyzer/badwolf',
        'git@bitbucket.org:deepanalyzer/badwolf.git',
        None,
        'pullrequest',
        'message',
        {'commit': {'hash': '000000'}},
        {'commit': {'hash': '111111'}},
        pr_id=1
    )
    spec = Specification()
    spec.linters.append('flake8')
    lint = LintProcessor(context, spec, os.path.join(FIXTURES_PATH, 'flake8'))
    patch = PatchSet(diff.split('\n'))
    with mock.patch.object(lint, 'load_changes') as load_changes,\
            mock.patch.object(lint, 'update_build_status') as build_status,\
            mock.patch.object(lint, '_report') as report:
        load_changes.return_value = patch
        build_status.return_value = None
        report.return_value = None
        lint.problems.set_changes(patch)
        lint.process()

        assert load_changes.called

    assert len(lint.problems) == 1
    problem = lint.problems[0]
    assert problem.filename == 'a.py'
    assert problem.line == 6
