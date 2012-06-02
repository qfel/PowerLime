from __future__ import division

import ast
import json
import os
import os.path
import re

import sublime

from collections import defaultdict
from difflib import SequenceMatcher
from functools import partial
from inspect import getargspec
from itertools import groupby
from operator import ge, le
from string import Template
from subprocess import PIPE, Popen
from types import BuiltinMethodType, MethodType

from sublime_plugin import ApplicationCommand, EventListener, TextCommand, \
    WindowCommand, application_command_classes, text_command_classes, \
    window_command_classes


def syntax_name(view):
    syntax = os.path.basename(view.settings().get('syntax'))
    syntax = os.path.splitext(syntax)[0]
    return syntax.lower()


class PythonImportFormatter(object):
    ''' Sorts Python imports '''

    def __init__(self, wrap_at=None, indent=None, min_group_size=None):
        self.wrap_at = wrap_at
        self.indent = indent or ' '
        self.min_group_size = min_group_size or float('inf')

    def _break_lines(self):
        if self.wrap_at is None:
            return

        output = []
        for line in self._output:
            while len(line) > self.wrap_at:
                i = self.wrap_at - 2
                while i > 0:
                    if line[i] == ' ':
                        output.append(line[:i] + ' \\')
                        line = self.indent + line[i + 1:]
                        break
                    i -= 1
                else:
                    break
            output.append(line)
        self._output = output

    def _indent(self, cols):
        n = len(self.indent)
        return (self.indent * ((cols + n - 1) // n))[:cols]

    def _format_aliases(self, aliases):
        return u', '.join(
            alias.name if alias.asname is None else
                u'{0} as {1}'.format(alias.name, alias.asname)
            for alias in aliases
        )

    def _format_import(self, imp):
        return u'{0}import {1}'.format(
            self._indent(imp.col_offset),
            self._format_aliases(imp.names)
        )

    def _format_from_import(self, imp):
        return u'{0}from {1} import {2}'.format(
            self._indent(imp.col_offset),
            '.' * imp.level + (imp.module or ''),
            self._format_aliases(imp.names)
        )

    def _sort_aliases(self, aliases):
        aliases.sort(key=lambda alias: alias.name)

    def _sort_imports(self, imports):
        for imp in imports:
            self._sort_aliases(imp.names)
        imports.sort(key=lambda imp: imp.names[0].name)

    def _sort_from_imports(self, imports):
        for imp in imports:
            self._sort_aliases(imp.names)
        imports.sort(key=lambda imp: (imp.level, imp.module))

    def _import_key(self, imp):
        if len(imp.names) == 1:
            return imp.names[0].name.split('.', 1)[0]
        else:
            return None

    def _from_import_key(self, imp):
        return imp.level, (imp.module or '').split('.', 1)[0]

    def _output_formatted(self, imports, formatter, keyfunc):
        def flush():
            if group_size >= self.min_group_size and group_start is not None:
                self._output.insert(group_start, '')

        key = None
        group_size = 0
        for imp in imports:
            new_key = keyfunc(imp)
            if key != new_key:
                flush()
                key = new_key
                if group_size >= self.min_group_size:
                    self._output.append('')
                    group_start = None
                else:
                    group_start = len(self._output)
                group_size = 1
            else:
                group_size += 1
            self._output.append(formatter(imp))
        flush()

    def format(self, src):
        self._output = []
        for isspace, lines in groupby(src.split('\n'),
                lambda s: s.isspace() or not s):
            if not isspace:
                lines = list(lines)
                try:
                    src = ast.parse(u'\n'.join(lines))
                except SyntaxError:
                    self._output.extend(lines)
                    continue
                except TypeError:
                    self._output.extend(lines)
                    continue

                imports = []
                from_imports = []
                for stmt in src.body:
                    if isinstance(stmt, ast.Import):
                        imports.append(stmt)
                    elif isinstance(stmt, ast.ImportFrom):
                        from_imports.append(stmt)
                    else:
                        self._output.extend(lines)
                        break
                else:
                    self._sort_imports(imports)
                    self._sort_from_imports(from_imports)
                    self._output_formatted(imports, self._format_import,
                        self._import_key)
                    if imports and from_imports:
                        self._output.append('')
                    self._output_formatted(from_imports,
                        self._format_from_import, self._from_import_key)
            else:
                self._output.extend(lines)

        self._break_lines()
        return u'\n'.join(self._output)


class SortPythonImportsCommand(TextCommand):
    ''' Sort Python imports '''

    def run(self, edit):
        view = self.view
        settings = view.settings()
        kwargs = {'min_group_size': settings.get('sort_py_imports_group', 2)}
        rulers = settings.get('rulers')
        if rulers is not None:
            kwargs['indent'] = ' ' * settings.get('tab_size', 4)
            kwargs['wrap_at'] = min(rulers)
        formatter = PythonImportFormatter(**kwargs)

        for region in view.sel():
            region = view.line(region)
            view.replace(edit, region, formatter.format(view.substr(region)))

    def is_enabled(self):
        return syntax_name(self.view).lower() == 'python'


class RunCommand(object):
    @staticmethod
    def _parse_docstring(doc, max_lines):
        for i, line in enumerate(doc.split('\n')):
            line = line.strip()
            if line:
                if i == max_lines:
                    yield '...'
                    return
                yield line

    @classmethod
    def _describe_command_args(cls, func):
        spec = getargspec(func)
        args = spec.args[:]
        if isinstance(func, (MethodType, BuiltinMethodType)):
            del args[0]
        del args[0:cls.SKIP_ARGS]

        if args:
            defaults = (spec.defaults or [])[-len(args):]
        else:
            defaults = []

        desc = args[:(-len(defaults) or None)]
        if defaults:
            desc.extend('{0}={1}'.format(args[i], json.dumps(defaults[i]))
                for i in xrange(len(defaults)))
        if spec.varargs:
            desc.append('{0}..'.format(spec.varargs))
        if spec.keywords:
            desc.append('[{0}]'.format(spec.keywords))
        return ', '.join(desc)

    @classmethod
    def _generate_doc(cls, func):
        desc = cls._describe_command_args(func)
        if desc:
            return ['Arguments: ' + desc]
        else:
            return ['This command takes no arguments']

    @classmethod
    def _command_info(cls, cmd_cls):
        SUFFIX = 'Command'

        info = cmd_cls.__name__
        if info.endswith(SUFFIX):
            info = info[:-len(SUFFIX)]

        info = [re.sub(r'([a-z])([A-Z])', r'\1_\2', info).lower()]
        if cmd_cls.__doc__ is not None:
            argdesc = cls._describe_command_args(cmd_cls.run)
            if argdesc:
                info.append('Arguments: ' + argdesc)
                max_lines = 2
            else:
                max_lines = 3
            info.extend(cls._parse_docstring(cmd_cls.__doc__, max_lines))
        else:
            info.extend(cls._generate_doc(cmd_cls.run))
        return info

    def _handle_command(self, commands, index):
        if index == -1:
            return

        cmd = commands[index][0]
        run = self.COMMANDS[index].run
        argdesc = self._describe_command_args(run)
        if argdesc:
            self.get_window().show_input_panel(argdesc + ':', '',
                partial(self._handle_complex_command, cmd, run), None, None)
        else:
            self.get_object().run_command(cmd)

    def _handle_complex_command(self, cmd, run, args):
        args = args.strip()
        if args:
            try:
                raw_args = json.loads('[{0}]'.format(args))
            except Exception as e:
                sublime.error_message(unicode(e))
                return

            args = {}
            spec = getargspec(run)
            skip_args = isinstance(run, (MethodType, BuiltinMethodType)) + \
                self.SKIP_ARGS

            i = 0
            while skip_args + i < len(spec.args):
                if i >= len(raw_args):
                    sublime.error_message('Value for {0} is required'.format(
                        spec.args[skip_args + i]))
                    return
                args[spec.args[skip_args + i]] = raw_args[i]
                i += 1

            if i < len(raw_args):
                if not spec.varargs:
                    sublime.error_message('Too many arguments')
                    return
                args[spec.varargs] = raw_args[i:]
        else:
            args = None
        self.get_object().run_command(cmd, args)

    def run(self):
        commands = [self._command_info(cls) for cls in self.COMMANDS]
        self.get_window().show_quick_panel(commands,
            partial(self._handle_command, commands))


class RunTextCommandCommand(RunCommand, TextCommand):
    COMMANDS = text_command_classes
    SKIP_ARGS = 1

    def get_window(self):
        return self.view.window()

    def get_object(self):
        return self.view

    def run(self, edit):
        RunCommand.run(self)


class RunWindowCommandCommand(RunCommand, WindowCommand):
    COMMANDS = window_command_classes
    SKIP_ARGS = 0

    def get_window(self):
        return self.window

    def get_object(self):
        return self.window


class RunApplicationCommandCommand(RunCommand, ApplicationCommand):
    COMMANDS = application_command_classes
    SKIP_ARGS = 0

    def get_window(self):
        return sublime.active_window()

    def get_object(self):
        return sublime


class ChangesCommandBase(object):
    INSERTS_KEY = 'mark_diff_ins'
    REPLACES_KEY = 'mark_diff_repl'

    REGION_KEYS = (INSERTS_KEY, REPLACES_KEY)

    def _erase_regions(self, view):
        for key in self.REGION_KEYS:
            view.erase_regions(key)


class MarkChangesCommand(ChangesCommandBase, TextCommand):
    ''' Mark changes between current text and file saved on disk '''

    class UserString(str):
        pass

    class UserUnicode(str):
        pass

    @classmethod
    def _split_lines(cls, src):
        lines = []
        sep = '\n'
        i = 0
        if isinstance(src, unicode):
            StrClass = cls.UserUnicode
        else:
            StrClass = cls.UserString
        while True:
            j = src.find(sep, i)
            if j == -1:
                j = len(sep)
            line = StrClass(src[i:j])
            line.offset = i
            lines.append(line)
            if j == len(sep):
                break
            i = j + len(sep)
        return lines

    def run(self, edit):
        view = self.view
        with open(view.file_name(), 'rb') as f:
            src = self._split_lines(f.read())
        dst = self._split_lines(view.substr(sublime.Region(0, view.size())))
        matcher = SequenceMatcher(str.isspace, src, dst)

        inserts = []
        replaces = []
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == 'insert':
                regions = inserts
            elif op == 'replace':
                regions = replaces
            else:
                continue
            for j in xrange(j1, j2):
                regions.append(sublime.Region(dst[j].offset,
                    dst[j].offset + len(dst[j])))

        self._erase_regions(self.view)
        view.add_regions(self.INSERTS_KEY, inserts, 'markup.inserted.diff',
            'dot', sublime.HIDDEN)
        view.add_regions(self.REPLACES_KEY, replaces, 'markup.deleted.diff',
            'dot', sublime.HIDDEN)

    def is_enabled(self):
        return self.view.file_name() is not None and self.view.is_dirty()


class UnmarkChangesCommand(ChangesCommandBase, TextCommand):
    ''' Unmark all marked changes '''

    def run(self, edit):
        self._erase_regions(self.view)

    def is_enabled(self):
        for key in self.REGION_KEYS:
            if self.view.get_regions(key):
                return True
        return False


class AutomaticUnmarker(ChangesCommandBase, EventListener):
    def on_modified(self, view):
        self._erase_regions(view)

    def on_post_save(self, view):
        self._erase_regions(view)


class ChangeLayoutCommand(WindowCommand):
    ''' Set layout to custom numbers of rows per column '''

    def run(self, rows_per_col):
        rows = list(set(i / n for n in rows_per_col for i in xrange(n + 1)))
        rows.sort()

        n = len(rows_per_col)
        cols = [i / n for i in xrange(n + 1)]

        cells = [
            [
                i, rows.index(j / rows_per_col[i]),
                i + 1, rows.index((j + 1) / rows_per_col[i])
            ]
            for i in xrange(len(rows_per_col))
            for j in xrange(rows_per_col[i])
        ]

        self.window.set_layout({
            'rows': rows,
            'cols': cols,
            'cells': cells
        })


class SwitchViewInGroupCommand(WindowCommand):
    ''' Switch between views in same group '''

    def run(self, delta):
        win = self.window
        group, index = win.get_view_index(self.window.active_view())
        views = win.views_in_group(group)
        win.focus_view(views[(index + delta) % len(views)])

    def is_enabled(self):
        win = self.window
        return bool(win.views_in_group(win.active_group()))


class SwitchGroupCommand(WindowCommand):
    ''' Switch groups '''

    def run(self, delta):
        win = self.window
        win.focus_group((win.active_group() + delta) % win.num_groups())

    def is_enabled(self):
        return self.window.num_groups() > 1


class SwitchGroupTwoDimCommand(WindowCommand):
    ''' Switch groups 2D '''

    def run(self, edge):
        win = self.window
        cells = win.get_layout()['cells']
        group = self._find_adjacent(cells, cells[win.active_group()], edge)
        win.focus_group(group)

    def is_enabled(self):
        return self.window.num_groups() > 1

    def _find_adjacent(self, cells, cell, component):
        if len(component) != 2:
            raise ValueError('Invalid component: ' + component)
        if component[0] == 'x':
            proj_scalar = 0
            proj_range = (1, 3)
        elif component[0] == 'y':
            proj_scalar = 1
            proj_range = (0, 2)
        else:
            raise ValueError('Invalid component: ' + component)
        if component[1] not in '12':
            raise ValueError('Invalid component: ' + component)
        proj_scalar += int(component[1]) * 2 - 2

        a1 = cell[proj_range[0]]
        b1 = cell[proj_range[1]]

        scalar = cell[proj_scalar]
        proj_scalar = (proj_scalar + 2) % 4
        if proj_scalar < 2:
            pred = le
        else:
            pred = ge

        best = None
        for i in xrange(len(cells)):
            a2 = cells[i][proj_range[0]]
            b2 = cells[i][proj_range[1]]
            if b2 <= a1 or b1 <= a2:
                continue
            if not pred(cells[i][proj_scalar], scalar):
                continue
            if best is not None and (
                    pred(cells[i][proj_scalar], cells[best][proj_scalar]) or
                    a2 > cells[best][proj_range[0]]
                ):
                continue
            best = i

        return best


class GroupViewsCommand(WindowCommand):
    ''' Move views to groups based on regular expressions '''

    @staticmethod
    def _normalize_path(path):
        path = os.path.normcase(path)
        if os.sep != '/':
            path = path.replace(os.sep, '/')
        return path

    def run(self, filters):
        win = self.window
        org_view = win.active_view()

        args = {'path': self._normalize_path(org_view.file_name())}
        args['dir'], args['file'] = os.path.split(args['path'])
        args['base'], args['ext'] = os.path.splitext(args['file'])
        for k, v in args.iteritems():
            args[k] = re.escape(v)

        groups = range(len(filters) - 1, -1, -1)
        for i in xrange(len(filters)):
            if not isinstance(filters[i], list):
                filters[i] = filters[i], groups.pop()
            else:
                assert len(filters[i]) == 2
                groups.remove(filters[i][1])

        for view in reversed(win.views()):
            path = view.file_name()
            if path is None:
                continue
            path = self._normalize_path(path)

            for regex, group in filters:
                regex = Template(regex).safe_substitute(args)
                if re.search(regex, path):
                    win.set_view_index(view, group, 0)
                    break

        win.focus_view(org_view)


class HelpCommand(TextCommand):
    ''' Display internal [Python] help index '''

    _index = {}

    def run(self, edit, auto_select=True):
        self._syntax = syntax_name(self.view)

        sel = self.view.sel()
        if len(sel) != 1:
            return sublime.error_message('Multiple selections not supported')

        sel = sel[0]
        if sel.empty():
            if auto_select:
                sym = self.view.substr(self.view.word(sel))
            else:
                sym = False
        else:
            sym = self.view.substr(sel)

        self._path = []
        self._choice_index = self._get_index()
        if sym in self._choice_index:
            self._choice_index = self._choice_index[sym]
            self._path.append(sym)

        self._disambiguate_symbol()

    def is_enabled(self):
        self._syntax = syntax_name(self.view)
        return bool(self._get_index_path())

    def _get_index_path(self):
        return self.view.settings().get('help_index', {}).get(self._syntax)

    def _get_index(self):
        index = self._index.get(self._syntax)
        if index is not None:
            return index

        path = self._get_index_path()
        if path is None:
            return None

        index = self._index[self._syntax] = self._load_index(path)
        return index

    def _load_index(self, file_name):
        def recursive_dict():
            return defaultdict(recursive_dict)

        index = recursive_dict()
        path = []
        for line in open(file_name):
            sym = line.lstrip()
            indent = len(line) - len(sym)
            sym = sym.rstrip()
            while len(path) > indent:
                path.pop()
            path.append(sym)
            for i in xrange(len(path)):
                sub_index = index
                for sym in path[i::-1]:
                    sub_index = sub_index[sym]
                sub_index[None] = None

        return index

    def _disambiguate_symbol(self):
        if self._choice_index is None:
            return self._show_doc()
        while len(self._choice_index) == 1:
            sym, next_index = next(self._choice_index.iteritems())
            if next_index is None:
                return self._show_doc()
            self._choice_index = next_index
            self._path.append(sym)

        has_final = False
        self._labels = []
        self._choices = []
        for sym, sub_index in self._choice_index.iteritems():
            if sub_index is not None:
                self._labels.append(sym)
                self._choices.append(sub_index)
            else:
                has_final = True

        if has_final:
            self._labels.append(u'<{0}>'.format(
                self._get_current_symbol()))
            self._choices.append(None)

        self.view.window().show_quick_panel(self._labels, self._on_user_choice)

    def _get_current_symbol(self):
        return u'.'.join(reversed(self._path))

    def _on_user_choice(self, index):
        if index == -1:
            return

        if self._choices[index] is None:
            return self._show_doc()

        self._choice_index = self._choices[index]
        self._path.append(self._labels[index])
        self._disambiguate_symbol()

    def _show_doc(self):
        sym = self._get_current_symbol()
        doc = self._get_doc(sym)
        if doc is None:
            return sublime.error_message('Internal help system error')

        win = sublime.active_window()
        output = win.new_file()
        output.set_scratch(True)
        output.set_name('Help on ' + sym)

        edit = output.begin_edit()
        output.erase(edit, sublime.Region(0, output.size()))
        output.insert(edit, 0, doc)
        output.end_edit(edit)

        output.set_read_only(True)

        settings = output.settings()
        settings.set('rulers', [])
        settings.set('line_numbers', False)
        settings.set('spell_check', False)

    def _get_doc(self, sym):
        try:
            proc = Popen(['pydoc', sym], stdout=PIPE)
        except OSError:
            return None
        output = proc.stdout.read()
        if proc.wait() != 0:
            return None
        return output


class MoveToVisibleCommand(TextCommand):
    def run(self, edit, position):
        def set_sel(pos):
            sel = view.sel()
            sel.clear()
            sel.add(sublime.Region(pos))

        view = self.view
        visible = view.visible_region()

        if position == 'begin':
            set_sel(visible.begin())
        elif position == 'end':
            set_sel(visible.end())
        elif position == 'center':
            r1, _ = view.rowcol(visible.begin())
            r2, _ = view.rowcol(visible.end())
            set_sel(view.text_point((r1 + r2) // 2, 0))


class MoveAllToGroupCommand(WindowCommand):
    def run(self, group):
        win = self.window

        active_group = win.active_group()
        if group == 'next':
            group = (active_group + 1) % win.num_groups()
        elif group == 'prev':
            group = (active_group - 1) % win.num_groups()

        for view in reversed(win.views_in_group(active_group)):
            win.set_view_index(view, group, 0)

    def is_enabled(self):
        return self.window.active_view() is not None
