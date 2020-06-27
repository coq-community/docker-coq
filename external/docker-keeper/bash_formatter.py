#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2020  Érik Martin-Dorel
#
# Contributed under the terms of the MIT license,
# cf. <https://spdx.org/licenses/MIT.html>

from string import Formatter
import _string
import re


def translate(glob, greedy=False):
    """Translate a simple glob expression to a (non-anchored) regexp."""
    qmark = '.'
    if greedy:
        star = '.*'
    else:
        star = '.*?'

    inner = lambda s: qmark.join(map(re.escape, s.split('?')))  # noqa: E731

    return star.join(map(inner, glob.split('*')))


def translate_prefix(glob, greedy=False):
    """Translate a simple glob expression to a (left)anchored regexp."""
    return '^' + translate(glob, greedy)


def reverse(text):
    return text[::-1]


class BashLike(Formatter):
    """Refine string.format(dict), allowing {var[bash-like-patterns]}.

    In particular:
    {var[0:7]}
    {var[%.*]}
    {var[%%.*]}
    {var[//glob/str]}
    """
    # New implementation of
    # <https://github.com/python/cpython/blob/919f0bc/Lib/string.py#L267-L280>:
    def get_field(self, field_name, args, kwargs):
        first, rest = _string.formatter_field_name_split(field_name)

        obj = self.get_value(first, args, kwargs)

        for is_attr, i in rest:
            if is_attr:
                # hide private fields
                if i.startswith('_'):
                    obj = ''
                else:
                    obj = getattr(obj, i)
            else:
                mslice = re.match('^([0-9]+):([0-9]+)$', i)
                msuffixgreedy = re.match('^%%(.+)$', i)
                msuffix = re.match('^%(.+)$', i)  # to test after greedy
                msed = re.match('^//([^/]+)/(.*)$', i)
                # Note: we could also define
                # mprefixgreedy = re.match('^##(.+)$', i)
                # mprefix = re.match('^#(.+)$', i)
                if mslice:
                    a, b = map(int, mslice.groups())
                    obj = obj[a:b]
                elif msuffixgreedy:
                    suffix = msuffixgreedy.groups()[0]
                    prefix = translate_prefix(reverse(suffix), True)
                    obj = reverse(re.sub(prefix, '', reverse(obj), count=1))
                elif msuffix:
                    suffix = msuffix.groups()[0]
                    prefix = translate_prefix(reverse(suffix), False)
                    obj = reverse(re.sub(prefix, '', reverse(obj), count=1))
                elif msed:
                    glob, dest = msed.groups()
                    regexp = translate(glob, True)
                    obj = re.sub(regexp, dest, obj, count=0)
                else:
                    obj = obj[i]

        return obj, first


###############################################################################
# Test suite, cf. <https://docs.python-guide.org/writing/tests/>
# $ pip3 install pytest
# $ py.test bash_formatter.py

class Dummy():
    _val = None

    def __init__(self, val):
        self._val = val


def test_reverse():
    assert reverse('12345') == '54321'


def test_translate():
    assert translate('?????678-*.txt') == '.....678\\-.*?\\.txt'
    assert translate('?????678-*.txt', True) == '.....678\\-.*\\.txt'


def test_BashLike():
    b = BashLike()
    assert b.format('A{var[2:4]}Z', var='abcde') == 'AcdZ'
    assert b.format('{s[0:7]}', s='1234567890abcdef') == '1234567'
    assert b.format('{s[%.*]}', s='8.10.0') == '8.10'
    assert b.format('{s[%%.*]}', s='8.10.0') == '8'
    assert b.format('{s[%???]}', s='3.14159') == '3.14'
    assert b.format('{obj._val}', obj=Dummy(4)) == ''
    assert b.format('V{matrix[coq][//-/+]}', matrix={'coq': '8.12-alpha'}) == \
        'V8.12+alpha'
