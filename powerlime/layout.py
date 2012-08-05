from __future__ import division

from operator import ge, le

from sublime import Region
from sublime_plugin import TextCommand, WindowCommand


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
    ''' Switch between groups '''

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


class MoveToVisibleCommand(TextCommand):
    ''' Moves cursor to specified visible part of displayed file '''

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
        else:
            raise ValueError('Invalid position: ' + position)
