# clize -- A command-line argument parser for Python
# Copyright (C) 2013 by Yann Kaiser <kaiser.yann@gmail.com>
# See COPYING for details.

"""various"""

import os
from functools import update_wrapper
import itertools
import textwrap

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

import six


class _Unset(object):
    __slots__ = ()
    def __repr__(self):
        return '<unset>'
UNSET = _Unset()
del _Unset

try:
    zip_longest = itertools.zip_longest
except AttributeError:
    zip_longest = itertools.izip_longest

def identity(x=None):
    return x

def name_py2cli(name, kw=False):
    name = name.strip('_').replace('_', '-')
    if kw:
        if len(name) > 1:
            return '--' + name
        else:
            return '-' + name
    else:
        return name

def name_cli2py(name, kw=False):
    return name.strip('-').replace('-', '_')

def name_type2cli(typ):
    try:
        return typ.clize_type_name
    except AttributeError:
        pass
    if typ is identity or typ in six.string_types:
        return 'STR'
    else:
        return typ.__name__.upper()

def maybe_iter(x):
    try:
        iter(x)
    except TypeError:
        return x,
    else:
        if isinstance(x, six.string_types):
            return x,
    return x

def dict_from_names(obj, receiver=None, func=identity):
    try:
        obj.items
    except AttributeError:
        pass
    else:
        if receiver is None:
            return obj
        else:
            receiver.update(obj)
            return receiver
    if receiver is None:
        receiver = OrderedDict()
    receiver.update((func(x.__name__), x) for x in maybe_iter(obj))
    return receiver

class property_once(object):
    def __init__(self, func):
        update_wrapper(self, func)
        self.func = func
        self.key = func.__name__

    def __get__(self, obj, owner):
        if obj is None:
            return self
        try:
            return obj.__dict__[self.key] # could happen if we've been
                                          # assigned to multiple names
        except KeyError:
            ret = obj.__dict__[self.key] = self.func(obj)
            return ret

    def __repr__(self):
        return '<property_once from {0!r}>'.format(self.func)


def bound(min, val, max):
    if min is not None and val < min:
        return min
    elif max is not None and val > max:
        return max
    else:
        return val


class _FormatterRow(object):
    def __init__(self, columns, cells):
        self.columns = columns
        self.cells = cells

    def __iter__(self):
        return iter(self.cells)

    def __repr__(self):
        return "{0}({1.columns!r}, {1.cells!r})".format(
            type(self).__name__, self)

    def formatter_lines(self):
        return self.columns.format_cells(self.cells)


def process_widths(widths, max_width):
    for w in widths:
        if isinstance(w, float):
            yield int(w * max_width)
        else:
            yield w


class _FormatterColumns(object):
    def __init__(self, formatter, num, spacing, align,
                 wrap, min_widths, max_widths):
        self.formatter = formatter
        self.num = num
        self.spacing = spacing
        self.align = align or '<' * num
        self.wrap = wrap or (False,) + (True,) * (num - 1)
        self.min_widths = min_widths or (2,) * num
        self.max_widths = max_widths or (.25,) + (None,) * (num - 1)
        self.rows = []
        self.finished = False

    def __enter__(self):
        return self

    def append(self, *cells):
        if len(cells) != self.num:
            raise ValueError('expected {0} cells but got {1}'.format(
                             self.num, len(cells)))
        row = _FormatterRow(self, cells)
        self.rows.append(row)
        self.formatter.append_raw(row)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finished = True
        self.widths = list(self.compute_widths())

    def compute_widths(self):
        used = len(self.spacing) * (self.num - 1)
        space_left = self.formatter.max_width - used
        min_widths = list(process_widths(self.min_widths, space_left))
        max_widths = list(process_widths(self.max_widths, space_left))
        maxlens = [sorted(len(s) for s in col) for col in zip(*self.rows)]
        for i, maxlen in enumerate(maxlens):
            space_left = (
                self.formatter.max_width
                - used - sum(min_widths[i+1:]))
            max_width = bound(None, space_left, max_widths[i])
            if not self.wrap[i]:
                while maxlen[-1] > max_width:
                    maxlen.pop()
                    if not maxlen:
                        maxlen.append(min_widths[i])
                        break
            width = bound(min_widths[i], maxlen[-1], max_width)
            used += width
            yield width


    def format_cells(self, cells):
        wcells = (self.format_cell(*args) for args in enumerate(cells))
        return (self.spacing.join(cline).rstrip()
                for cells in zip_longest(*wcells)
                for cline in self.match_lines(cells)
                )

    def format_cell(self, i, cell):
        if self.wrap[i] or len(cell) <= self.widths[i]:
            width = self.widths[i]
        else:
            width = sum(self.widths[i:]) + len(self.spacing) * (self.num-i-1)
        for line in textwrap.wrap(cell, width):
            yield '{0:{1}{2}}'.format(line, self.align[i], width)

    def match_lines(self, cells):
        ret = []
        for i, cell in enumerate(cells):
            if cell is None:
                cell = ' ' * self.widths[i]
            ret.append(cell)
            if len(cell) > self.widths[i]:
                yield ret
                if i + 1 == self.num:
                    return
                ret = [' ' * (sum(self.widths[:i+1]) + len(self.spacing) * i)]
        yield ret


class _FormatterIndent(object):
    def __init__(self, formatter, indent):
        self.formatter = formatter
        self.indent = indent

    def __enter__(self):
        self.formatter._indent += self.indent
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.formatter._indent -= self.indent


def get_terminal_width():
    try:
        return os.get_terminal_size().columns
    except (AttributeError, OSError):
        return 78


class Formatter(object):
    delimiter = '\n'

    def __init__(self, max_width=None):
        self.max_width = (
            get_terminal_width() if max_width is None else max_width)
        self.wrapper = textwrap.TextWrapper()
        self.lines = []
        self._indent = 0

    def append(self, line, indent=0):
        self.wrapper.width = self.get_width(indent)
        for wline in self.wrapper.wrap(line):
            self.append_raw(wline, indent=indent)

    def append_raw(self, line, indent=0):
        self.lines.append((self._indent + indent, line))

    def get_width(self, indent=0):
        return self.max_width - self._indent - indent

    def new_paragraph(self):
        if self.lines and self.lines[-1][1]:
            self.lines.append((0, ''))

    def extend(self, iterable):
        if not isinstance(iterable, Formatter):
            iterator = ((0, line) for line in iterable)
        else:
            iterator = iter(iterable)
        try:
            first = next(iterator)
        except StopIteration:
            return
        if not first[1]:
            self.new_paragraph()
        else:
            self.append_raw(first[1], first[0])
        for indent, line in iterator:
            self.append_raw(line, indent)

    def indent(self, indent=2):
        return _FormatterIndent(self, indent)

    def columns(self, num=2, spacing='   ', align=None,
                wrap=None, min_widths=None, max_widths=None):
        return _FormatterColumns(
            self, num, spacing, align,
            wrap, min_widths, max_widths)

    def __str__(self):
        if self.lines and not self.lines[-1][1]:
            lines = self.lines[:-1]
        else:
            lines = self.lines
        return self.delimiter.join(
            ' ' * indent + line
            for indent, line_ in lines
            for line in self.convert_line(line_)
            )

    def convert_line(self, line):
        try:
            lines_getter = line.formatter_lines
        except AttributeError:
            yield six.text_type(line)
        else:
            for line in lines_getter():
                yield six.text_type(line)

    def __iter__(self):
        return iter(self.lines)

