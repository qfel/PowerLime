from __future__ import division

from operator import ge, le

from sublime import Region
from sublime_plugin import TextCommand, WindowCommand


class FocusGroupAtCommand(WindowCommand):
    ''' Focus group at specified visual position.

    position: a combination of edges (l, r, t, b for left, right, top and
    bottom respectively) specifying one of 9 positions that overlaps the group
    user wants to select. The layout is:

    lt t tr
    l     r
    lb b br
    '''

    def run(self, position):
        def get_index(types, offsets):
            count = len(offsets) - 1
            if count < 1 or count > 3:
                raise ValueError('Invalid offsets')

            if types[0] in position:
                return 0
            elif types[1] in position:
                return count - 1
            elif count == 3:
                return 1
            elif count == 1:
                return 0
            else:  # count == 2
                raise ValueError('Invalid position')

        layout = self.window.get_layout()
        y = get_index('tb', layout['rows'])
        x = get_index('lr', layout['cols'])
        for i, (x1, y1, x2, y2) in enumerate(layout['cells']):
            if x1 <= x < x2 and y1 <= y < y2:
                self.window.focus_group(i)
                break

    def is_enabled(self, position):
        def check(types, offsets):
            count = len(offsets) - 1
            if count in (1, 3):
                return True
            elif count == 2:
                return types[0] in position or types[1] in position
            else:
                raise ValueError('Invalid offsets')

        layout = self.window.get_layout()
        return check('tb', layout['rows']) and check('lr', layout['cols'])


class SetLayoutAutoCommand(WindowCommand):
    ''' Set layout to custom numbers of rows per column or columns per row.

    This is slightly less functional than builtin set_layout command (bound by
    default to Alt+Shift+<1..4>), but is much easier to pass correct arguments.
    This command is basically a set_layout wrapper that generates rows, cols and
    cells parameters based on more readable specification.
    '''

    def run(self, rows_per_col=None, cols_per_row=None, row_dir=1, col_dir=1):
        # Validate the arguments.
        if rows_per_col is None == cols_per_row is None:
            raise ValueError('Exactly one of rows_per_col and cols_per_row must'
                             ' be specified')
        if not (row_dir in (-1, 1) and col_dir in (-1, 1)):
            raise ValueError('')

        # Take care of symmetry.
        if rows_per_col is not None:
            counts = rows_per_col
            delta1 = col_dir
            delta2 = row_dir
        else:
            counts = cols_per_row
            delta1 = row_dir
            delta2 = col_dir

        # Generate sorted row and column offsets.
        n = len(counts)
        offsets1 = [i / n for i in xrange(n + 1)]
        offsets2 = list(set(i / n for n in counts for i in xrange(n + 1)))
        offsets2.sort()

        # Generate group cells (they may span more than one row or column). Cell
        # coordinates may be swapped, depending on whether the ordering is row-
        # or column- major.
        def auto_xrange(n, delta):
            if delta > 0:
                return xrange(0, n, delta)
            else:
                return xrange(n - 1, -1, delta)

        cells = []
        for i1 in auto_xrange(len(counts), delta1):
            for i2 in auto_xrange(counts[i1], delta2):
                cells.append([i1, offsets2.index(i2 / counts[i1]),
                              i1 + 1, offsets2.index((i2 + 1) / counts[i1])])

        # Set the layout, taking care of any symmetric transforms.
        if rows_per_col is not None:
            self.window.set_layout({
                'rows':  offsets2,
                'cols':  offsets1,
                'cells': cells
            })
        else:
            self.window.set_layout({
                'rows':  offsets1,
                'cols':  offsets2,
                'cells': [[y1, x1, y2, x2] for (x1, y1, x2, y2) in cells]
            })


class SwitchViewInGroupCommand(WindowCommand):
    ''' Switch between views in the same group. '''

    def run(self, delta):
        win = self.window
        group, index = win.get_view_index(self.window.active_view())
        views = win.views_in_group(group)
        win.focus_view(views[(index + delta) % len(views)])

    def is_enabled(self):
        win = self.window
        return bool(win.views_in_group(win.active_group()))


class SwitchGroupCommand(WindowCommand):
    ''' Switch between groups. '''

    def run(self, delta):
        win = self.window
        win.focus_group((win.active_group() + delta) % win.num_groups())

    def is_enabled(self):
        return self.window.num_groups() > 1


class SwitchGroupTwoDimCommand(WindowCommand):
    ''' Switch groups based on their position. '''

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
                    a2 > cells[best][proj_range[0]]):
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


class ForkViewCommand(TextCommand):
    def run(self, edit, group=1, wrap=False, focus_new=True):
        assert group in (1, -1)

        window = self.view.window()
        num_groups = window.num_groups()
        if num_groups > 1:
            group = window.active_group() + group
            if group == -1:
                if wrap:
                    group = num_groups - 1
                else:
                    group = 1
            elif group == num_groups:
                if wrap:
                    group = 0
                else:
                    group = num_groups - 2
        else:
            group = 0

        window.run_command('clone_file')
        new_view = window.active_view()
        assert self.view.id() != new_view.id()
        window.run_command('move_to_group', {'group': group})

        new_view.sel().clear()
        new_view.sel().add_all(self.view.sel())
        new_view.set_viewport_position(self.view.viewport_position(), False)

        if not focus_new:
            window.focus_view(self.view)
