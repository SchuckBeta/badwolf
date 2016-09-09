# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals
import os
import io
import time
import uuid
import json
import shutil
import logging
import tempfile

import git
from flask import current_app, render_template, url_for
from requests.exceptions import ReadTimeout
from docker import Client
from docker.errors import APIError, DockerException

from badwolf.utils import to_text, to_binary
from badwolf.spec import Specification
from badwolf.lint.processor import LintProcessor
from badwolf.extensions import bitbucket
from badwolf.bitbucket import BuildStatus, BitbucketAPIError, PullRequest, Changesets


logger = logging.getLogger(__name__)


class TestContext(object):
    """Test context"""
    def __init__(self, repository, clone_url, actor, type,
                 message, source, target=None, rebuild=False,
                 pr_id=None, cleanup_lint=False):
        self.repository = repository
        self.clone_url = clone_url
        self.actor = actor
        self.type = type
        self.message = message
        self.source = source
        self.target = target
        self.rebuild = rebuild
        self.pr_id = pr_id
        self.cleanup_lint = cleanup_lint


class TestRunner(object):
    """Badwolf test runner"""

    def __init__(self, context, lock):
        self.context = context
        self.lock = lock
        self.repo_full_name = context.repository
        self.repo_name = context.repository.split('/')[-1]
        self.task_id = str(uuid.uuid4())
        self.commit_hash = context.source['commit']['hash']
        self.build_status = BuildStatus(
            bitbucket,
            self.repo_full_name,
            self.commit_hash,
            'badwolf/test',
            url_for('log.build_log', sha=self.commit_hash, _external=True)
        )

        self.docker = Client(
            base_url=current_app.config['DOCKER_HOST'],
            timeout=current_app.config['DOCKER_API_TIMEOUT'],
        )

    def run(self):
        start_time = time.time()
        self.branch = self.context.source['branch']['name']

        try:
            self.clone_repository()
        except git.GitCommandError as e:
            logger.exception('Git command error')
            self.update_build_status('FAILED', 'Git clone repository failed')
            content = ':broken_heart: **Git error**: {}'.format(to_text(e))
            if self.context.pr_id:
                pr = PullRequest(bitbucket, self.repo_full_name)
                pr.comment(
                    self.context.pr_id,
                    content
                )
            else:
                cs = Changesets(bitbucket, self.repo_full_name)
                cs.comment(
                    self.commit_hash,
                    content
                )

            shutil.rmtree(os.path.dirname(self.clone_path), ignore_errors=True)
            return

        if not self.validate_settings():
            shutil.rmtree(os.path.dirname(self.clone_path), ignore_errors=True)
            return

        if self.spec.scripts:
            self.update_build_status('INPROGRESS', 'Test in progress')
            docker_image_name, build_output = self.get_docker_image()
            if not docker_image_name:
                self.update_build_status('FAILED', 'Build or get Docker image failed')
                shutil.rmtree(os.path.dirname(self.clone_path), ignore_errors=True)
                return

            exit_code, output = self.run_tests_in_container(docker_image_name)
            if exit_code == 0:
                # Success
                logger.info('Test succeed for repo: %s', self.repo_full_name)
                self.update_build_status('SUCCESSFUL', '1 of 1 test succeed')
            else:
                # Failed
                logger.info(
                    'Test failed for repo: %s, exit code: %s',
                    self.repo_full_name,
                    exit_code
                )
                self.update_build_status('FAILED', '1 of 1 test failed')

            end_time = time.time()

            context = {
                'context': self.context,
                'task_id': self.task_id,
                'logs': to_text(output),
                'build_logs': to_text(build_output),
                'exit_code': exit_code,
                'branch': self.branch,
                'scripts': self.spec.scripts,
                'elapsed_time': int(end_time - start_time),
            }
            self.send_notifications(context)

        # Code linting
        if self.context.pr_id and self.spec.linters:
            lint = LintProcessor(self.context, self.spec, self.clone_path)
            lint.process()

        shutil.rmtree(os.path.dirname(self.clone_path), ignore_errors=True)

    def clone_repository(self):
        self.clone_path = os.path.join(
            tempfile.gettempdir(),
            'badwolf',
            self.task_id,
            self.repo_name
        )

        logger.info('Cloning %s to %s...', self.context.clone_url, self.clone_path)
        bitbucket.clone(self.repo_full_name, self.clone_path)

        if self.context.target:
            logger.info('Checkout branch %s', self.context.target['branch']['name'])
            git.Git(self.clone_path).checkout(self.context.target['branch']['name'])

            logger.info(
                'Merging branch %s into %s',
                self.context.source['branch']['name'],
                self.context.target['branch']['name']
            )
            git.Git(self.clone_path).merge(
                'origin/{}'.format(self.context.source['branch']['name'])
            )
        else:
            logger.info('Checkout commit %s', self.commit_hash)
            git.Git(self.clone_path).checkout(self.commit_hash)

    def validate_settings(self):
        conf_file = os.path.join(self.clone_path, current_app.config['BADWOLF_PROJECT_CONF'])
        if not os.path.exists(conf_file):
            logger.warning(
                'No project configuration file found for repo: %s',
                self.repo_full_name
            )
            return False

        self.spec = spec = Specification.parse_file(conf_file)
        if self.context.type == 'commit' and spec.branch and self.branch not in spec.branch:
            logger.info(
                'Ignore tests since branch %s test is not enabled. Allowed branches: %s',
                self.branch,
                spec.branch
            )
            return False

        if not spec.scripts and not spec.linters:
            logger.warning('No script(s) or linter(s) to run')
            return False
        return True

    def get_docker_image(self):
        docker_image_name = self.repo_full_name.replace('/', '-')
        output = []
        with self.lock:
            docker_image = self.docker.images(docker_image_name)
            if not docker_image or self.context.rebuild:
                dockerfile = os.path.join(self.clone_path, self.spec.dockerfile)
                build_options = {
                    'tag': docker_image_name,
                    'rm': True,
                }
                if not os.path.exists(dockerfile):
                    logger.warning(
                        'No Dockerfile: %s found for repo: %s, using simple runner image',
                        dockerfile,
                        self.repo_full_name
                    )
                    dockerfile_content = 'FROM messense/badwolf-test-runner\n'
                    fileobj = io.BytesIO(dockerfile_content.encode('utf-8'))
                    build_options['fileobj'] = fileobj
                else:
                    build_options['dockerfile'] = self.spec.dockerfile

                build_success = False
                logger.info('Building Docker image %s', docker_image_name)
                self.update_build_status('INPROGRESS', 'Building Docker image')
                res = self.docker.build(self.clone_path, **build_options)
                for line in res:
                    if b'Successfully built' in line:
                        build_success = True
                    log = to_text(json.loads(to_text(line))['stream'])
                    output.append(log)
                    logger.info('`docker build` : %s', log.strip())
                if not build_success:
                    return None, ''.join(output)

        return docker_image_name, ''.join(output)

    def run_tests_in_container(self, docker_image_name):
        command = '/bin/sh -c badwolf-run'
        environment = {}
        if self.spec.environments:
            # TODO: Support run in multiple environments
            environment = self.spec.environments[0]

        # TODO: Add more test context related env vars
        environment.update({
            'CI': 'true',
            'CI_NAME': 'badwolf',
            'BADWOLF_BRANCH': self.branch,
            'BADWOLF_COMMIT': self.commit_hash,
            'BADWOLF_BUILD_DIR': '/mnt/src',
            'BADWOLF_REPO_SLUG': self.repo_full_name,
        })
        if self.context.pr_id:
            environment['BADWOLF_PULL_REQUEST'] = to_text(self.context.pr_id)

        container = self.docker.create_container(
            docker_image_name,
            command=command,
            environment=environment,
            working_dir='/mnt/src',
            volumes=['/mnt/src'],
            host_config=self.docker.create_host_config(
                privileged=self.spec.privileged,
                binds={
                    self.clone_path: {
                        'bind': '/mnt/src',
                        'mode': 'rw',
                    },
                }
            )
        )
        container_id = container['Id']
        logger.info('Created container %s from image %s', container_id, docker_image_name)

        try:
            self.docker.start(container_id)
            self.update_build_status('INPROGRESS', 'Running tests in Docker container')
            exit_code = self.docker.wait(container_id, current_app.config['DOCKER_RUN_TIMEOUT'])
            output = self.docker.logs(container_id)
        except (APIError, DockerException, ReadTimeout) as e:
            exit_code = -1
            output = str(e)

            logger.exception('Docker error')
        finally:
            try:
                self.docker.remove_container(container_id, force=True)
            except (APIError, DockerException):
                logger.exception('Error removing docker container')

        return exit_code, output

    def update_build_status(self, state, description=None):
        try:
            self.build_status.update(state, description=description)
        except BitbucketAPIError:
            logger.exception('Error calling Bitbucket API')

    def send_notifications(self, context):
        exit_code = context['exit_code']
        template = 'test_success' if exit_code == 0 else 'test_failure'
        html = render_template('mail/' + template + '.html', **context)

        # Save log html
        log_dir = os.path.join(current_app.config['BADWOLF_LOG_DIR'], self.commit_hash)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        log_file = os.path.join(log_dir, 'build.html')
        with open(log_file, 'wb') as f:
            f.write(to_binary(html))

        notification = self.spec.notification
        emails = notification['emails']
        if not emails:
            return

        from badwolf.tasks import send_mail

        if exit_code == 0:
            subject = 'Test succeed for repository {}'.format(self.repo_full_name)
        else:
            subject = 'Test failed for repository {}'.format(self.repo_full_name)
        send_mail(emails, subject, html)
