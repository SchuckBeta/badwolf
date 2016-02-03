# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals
import logging

from badwolf.extensions import bitbucket
from badwolf.bitbucket import PullRequest, BitbucketAPIError
from badwolf.lint import Problems
from badwolf.lint.linters.eslint import ESLinter
from badwolf.lint.linters.flake8 import Flake8Linter
from badwolf.lint.linters.jscs import JSCSLinter


logger = logging.getLogger(__name__)


class LintProcessor(object):
    LINTERS = {
        'eslint': ESLinter,
        'flake8': Flake8Linter,
        'jscs': JSCSLinter,
    }

    def __init__(self, context, spec, working_dir):
        self.context = context
        self.spec = spec
        self.working_dir = working_dir
        self.problems = Problems()
        self.pr = PullRequest(bitbucket, context.repository)

    def load_changes(self):
        try:
            changes = self.pr.diff(self.context.pr_id)
        except BitbucketAPIError:
            logger.exception('Error fetch pull request diff')
            return

        self.problems.set_changes(changes)
        return changes

    def process(self):
        if not self.spec.linters:
            logger.info('No linters configured, ignore lint.')
            return

        patch = self.load_changes()
        if not patch:
            return

        lint_files = patch.added_files + patch.modified_files
        if not lint_files:
            logger.info('No changed files found, ignore lint')
            return

        files = [f.path for f in lint_files]
        self._execute_linters(files)
        self.problems.limit_to_changes()

        if len(self.problems):
            logger.info('Code lint result: %d problems found', len(self.problems))
            self._report()

    def _execute_linters(self, files):
        for name in self.spec.linters:
            linter_cls = self.LINTERS.get(name)
            if not linter_cls:
                logger.info('Linter %s not found, ignore.', name)
                continue

            linter = linter_cls(self.working_dir, self.problems)
            if not linter.is_usable():
                logger.info('Linter %s is not usable, ignore.', name)
                continue

            logger.info('Running %s code linter', name)
            linter.execute(files)

    def _report(self):
        try:
            comments = self.pr.all_comments(self.context.pr_id)
        except BitbucketAPIError:
            comments = []

        hash_set = set()
        for comment in comments:
            inline = comment.get('inline')
            if not inline:
                continue

            raw = comment['content']['raw']
            filename = inline['path']
            line_to = inline['to']
            hash_set.add(hash('{}{}{}'.format(filename, line_to, raw)))

        for problem in self.problems:
            content = ':broken_heart: **{}**: {}'.format(problem.linter, problem.message)
            comment_hash = hash('{}{}{}'.format(
                problem.filename,
                problem.line,
                content,
            ))
            if comment_hash in hash_set:
                continue

            try:
                self.pr.comment(
                    self.context.pr_id,
                    content,
                    line_to=problem.line,
                    filename=problem.filename
                )
            except BitbucketAPIError:
                pass
