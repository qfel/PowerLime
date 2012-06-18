from __future__ import division

import os
import os.path
import re

from sublime import HIDDEN, Region

from difflib import SequenceMatcher
from operator import ge, le
from string import Template

from sublime_plugin import EventListener, TextCommand, WindowCommand


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
        dst = self._split_lines(view.substr(Region(0, view.size())))
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
                regions.append(Region(dst[j].offset,
                    dst[j].offset + len(dst[j])))

        self._erase_regions(self.view)
        view.add_regions(self.INSERTS_KEY, inserts, 'markup.inserted.diff',
            'dot', HIDDEN)
        view.add_regions(self.REPLACES_KEY, replaces, 'markup.deleted.diff',
            'dot', HIDDEN)

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
