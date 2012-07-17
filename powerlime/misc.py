from __future__ import division

import os
import os.path
import re

from operator import ge, le
from string import Template

from sublime import Region, set_clipboard
from sublime_plugin import TextCommand, WindowCommand

from powerlime.util import CxxSpecificCommand


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


class MoveToVisibleCommand(TextCommand):
    def run(self, edit, position):
        def set_sel(pos):
            sel = view.sel()
            sel.clear()
            sel.add(Region(pos))

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


class CopyCurrentPath(CxxSpecificCommand):
    def run(self, edit, relative=True):
        path = self.view.file_name()
        if relative:
            for folder in self.view.window().folders():
                if path.startswith(folder + os.sep):
                    path = path[len(folder) + 1:]
                    break
        path = '#inlcude "{0}.h"'.format(os.path.splitext(path)[0])
        set_clipboard(path)


class GotoBlockCommand(TextCommand):
    def run(self, edit, mode):
        view = self.view
        sel = view.sel()
        if len(sel) != 1:
            return

        if mode == 'parent':
            fetch_line = self.prev_line
            is_match = self.is_parent_block
        elif mode in ('prev', 'next'):
            self.separated = False
            is_match = self.is_adjacent_block
            if mode == 'prev':
                fetch_line = self.prev_line
            else:
                fetch_line = self.next_line
        else:
            raise ValueError('Invalid mode: ' + mode)

        line = view.line(sel[0].b)
        self.indent = new_indent = self.get_indent(line)
        line = fetch_line(line)
        while line is not None:
            new_indent = self.get_indent(line)
            if is_match(new_indent if new_indent < line.size() else None):
                sel.clear()
                sel.add(Region(line.a + new_indent))
                view.show(sel)
                break
            line = fetch_line(line)

    def is_adjacent_block(self, indent):
        if indent is None:
            self.separated = True
        else:
            return indent < self.indent or (self.separated and
                indent == self.indent)

    def is_parent_block(self, indent):
        return indent is not None and indent < self.indent

    def get_indent(self, line):
        return re.match('[ \t]*', self.view.substr(line)).end()

    def prev_line(self, line):
        if line.a > 0:
            return self.view.line(line.a - 1)
        else:
            return None

    def next_line(self, line):
        line = self.view.line(line.b + 1)
        if line.a >= self.view.size():
            return None
        else:
            return line
