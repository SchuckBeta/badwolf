# badwolf

[What is badwolf](https://en.wikipedia.org/wiki/Bad_Wolf)

Features:

1. Run tests in Docker container
2. Supports multiple test scripts
3. Supports multiple after success/failure scripts
4. Supports E-mail notification

## Installation

```bash
$ python setup.py install
```

for development:

```bash
$ pip install -r dev-requirements.txt
$ python setup.py develop
```

## Configuration

There are several ways to configure badwolf, settings loading by order below:

1. Try to load from ``~/.badwolf.conf.py``
2. Try to use ``BADWOLF_CONF`` environment variable to set configuration file path and load it
3. Dict or a file path passed to ``badwolf.create_app`` function

## Run server for development

```bash
$ badwolf runserver
```

## Interactive shell

```bash
$ badwolf shell
```

## Run tests

```bash
$ py.test -v
```

Open interactive shell when test failed:

```bash
$ py.test -v -s --pdb
```

## Packaging and release

Build a distribution:

```bash
$ python setup.py release
```

Upload package to PyPI cloud:

```bash
twine upload -r bosondata dist/*
```

## Test configuration file

Configuration file use YAML format, filename should be ``.badwolf.yml``

Fields:

1. ``dockerfile``: Dockfile name for build docker image, ``str``
2. ``script``: Test scipt(s), ``str`` or ``list``
3. ``after_success``: command(s) to run after success, ``str`` or ``list``
4. ``after_failure``: command(s) to run after failure, ``str`` or ``list``
5. ``service``: service(s) to start before run script(s), ``str`` or ``list``
6. ``env``: envrionment variable(s), ``str`` or ``list``, only the first item will be used currently. Eg: ``env: X=1 Y=2 Z=3``

``Dockerfile`` should set ``FROM`` as ``messense/badwolf-test-runner`` in order to use [badwolf-runner](https://bitbucket.org/deepanalyzer/badwolf-runner/overview) to run tests.
But surely you can build your own docker image and use it as long as you put ``badwolf-runner`` binary in its executable path.
