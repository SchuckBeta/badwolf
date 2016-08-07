# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals
import six


class ObjectDict(dict):
    """Makes a dictionary behave like an object, with attribute-style access.
    """
    def __getattr__(self, key):
        if key in self:
            return self[key]
        return None

    def __setattr__(self, key, value):
        self[key] = value


def to_text(value, encoding='utf-8', errors='ignore'):
    """Convert value to unicode, default encoding is utf-8

    :param value: Value to be converted
    :param encoding: Desired encoding
    """
    if not value:
        return ''
    if isinstance(value, six.text_type):
        return value
    if isinstance(value, six.binary_type):
        return value.decode(encoding, errors)
    return six.text_type(value)


def yesish(value):
    """Typecast booleanish environment variables to :py:class:`bool`.

    :param string value: An environment variable value.
    :returns: :py:class:`True` if ``value`` is ``1``, ``true``, or ``yes``
        (case-insensitive); :py:class:`False` otherwise.
    """
    if isinstance(value, bool):
        return value
    return value.lower() in ('1', 'true', 'yes')
