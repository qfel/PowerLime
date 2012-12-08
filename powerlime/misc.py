import os
import os.path
import re

from collections import deque
from itertools import chain

from sublime import LITERAL, Region, TRANSIENT, set_clipboard, set_timeout, \
    windows
from sublime_plugin import EventListener, TextCommand


class CopyCurrentPathCommand(TextCommand):
    ''' Copies path of currently opened file to clipboard '''

    def run(self, edit, relative=True):
        path = self.view.file_name()
        if relative:
            path = os.path.realpath(path)
            for folder in self.view.window().folders():
                folder = os.path.realpath(folder)
                if path.startswith(folder + os.sep):
                    path = path[len(folder) + 1:]
                    break
        set_clipboard(path)


class FindAllVisible(TextCommand):
    def run(self, edit, compatible=True):
        if compatible:
            self.run_compatible()
        else:
            self.run_custom()

    def run_compatible(self):
        visible_region = self.view.visible_region()
        self.view.window().run_command('find_all_under')
        selections = self.view.sel()
        new_selections = []
        for sel in selections:
            if sel.intersects(visible_region):
                new_selections.append(sel)
        selections.clear()
        for sel in new_selections:
            selections.add(sel)

    def run_custom(self):
        view = self.view
        visible_region = view.visible_region()
        sel = view.sel()
        user_sel = list(sel)
        sel.clear()
        for single_sel in user_sel:
            if single_sel.empty():
                regions = self.find_iter(
                        visible_region,
                        r'\b{0}\b'.format(re.escape(view.substr(view.word(
                                single_sel)))),
                        0)
            else:
                regions = self.find_iter(visible_region,
                                         view.substr(single_sel),
                                         LITERAL)

            empty = True
            for region in regions:
                sel.add(region)
                empty = False
            if empty:
                sel.add(single_sel)

    def find_iter(self, region, pattern, flags):
        pos = region.begin()
        while True:
            match = self.view.find(pattern, pos, flags)
            if match is None or match.begin() >= region.end():
                break
            yield match
            pos = match.end()


class OpenFileAtCursorCommand(TextCommand):
    ''' Opens a file under the cursor '''

    def run(self, edit, transient=False):
        view = self.view
        if transient:
            flags = TRANSIENT
        else:
            flags = 0

        for sel in view.sel():
            if sel.empty():
                line = view.line(sel.a)
                file_names = self.get_file_names(
                    view.substr(line),
                    sel.a - line.a)
            else:
                file_names = [view.substr(sel)]

            window = view.window()
            search_paths = list(chain.from_iterable(
                window.folders() if dir_name is None else [dir_name]
                for dir_name in
                view.settings().get('open_search_paths', ['.', None])
            ))
            for file_name in file_names:
                if not os.path.isabs(file_name):
                    for dir_name in search_paths:
                        full_name = os.path.join(dir_name, file_name)
                        if os.path.isfile(full_name):
                            window.open_file(full_name, flags)
                            return
                    else:
                        continue
                else:
                    full_name = file_name
                window.open_file(full_name, flags)
                return

    def get_file_names(self, line, pos):
        def find_range(begin, end):
            try:
                i = line.rindex(begin, 0, pos)
                j = line.index(end, pos)
            except ValueError:
                return None
            else:
                i += 1
                file_names.append((j - i, line[i:j]))

        file_names = []
        find_range('"', '"')
        find_range("'", "'")
        find_range('<', '>')
        file_names.sort()
        left_match = re.match(r'[^\s:]*', line[pos - 1::-1])
        right_match = re.match(r'[^\s:]*', line[pos:])
        file_names.append((None,
                           line[pos - left_match.end():
                                pos + right_match.end()]))
        return [tup[1] for tup in file_names]


class OpenAncestorFileCommand(TextCommand):
    def run(self, edit, name, transient=True):
        path = self.view.file_name()
        components = []
        while True:
            head, tail = os.path.split(path)
            if not tail:
                components.append(head)
                break
            components.append(tail)
            path = head
        components.reverse()

        while components:
            components[-1] = name
            file_name = os.path.join(*components)
            if os.path.isfile(file_name):
                self.view.window().open_file(file_name, TRANSIENT if transient
                    else 0)
                break
            components.pop()


class FoldBySelectorCommand(TextCommand):
    def run(self, edit, selector, unfold=False):
        view = self.view
        regions = view.find_by_selector(selector)
        if not regions:
            return

        if not unfold:
            def add_region():
                end_fix = view.substr(end - 1) == '\n'
                new_regions.append(Region(begin, end - end_fix))

            begin = regions[0].a
            end = regions[0].b
            new_regions = []
            for i in xrange(1, len(regions)):
                region = Region(end, regions[i].a)
                if not view.substr(region).isspace():
                    add_region()
                    begin = regions[i].a
                end = regions[i].b
            add_region()
            self.view.fold(new_regions)
        else:
            self.view.unfold(regions)


class PositionHistoryState(object):
    __slots__ = ('stack', 'index')

    def __init__(self, stack, index):
        self.stack = stack
        self.index = index


def get_rows_set(view, regions):
    rows = set()
    for region in regions:
        rows.add(view.rowcol(region.a)[0])
        rows.add(view.rowcol(region.b)[0])
    return rows


class PositionHistoryManager(EventListener):
    states = {}
    next_id = 0

    def __init__(self):
        self.delay_gc()

    @classmethod
    def delay_gc(cls):
        set_timeout(cls.do_gc, 60 * 1000)

    @classmethod
    def do_gc(cls):
        view_ids = set(cls.states.iterkeys())
        for window in windows():
            for view in window.views():
                view_ids.discard(view.id())
        for view_id in view_ids:
            del cls.states[view_id]
        cls.delay_gc()

    @classmethod
    def on_modified(cls, view):
        history_size = view.settings().get('pwl_position_history_size')
        if not history_size:
            return

        view_id = view.id()
        replace = False
        state = cls.states.get(view_id)
        if state is not None:
            # Check if top state should be updated or new one should be pushed.
            sel_rows = get_rows_set(view, view.sel())
            old_rows = get_rows_set(view,
                                    view.get_regions(state.stack[state.index]))
            for row1 in sel_rows:
                for row2 in old_rows:
                    if abs(row1 - row2) <= 1:
                        replace = True
                        break
        else:
            state = cls.states[view_id] = PositionHistoryState(deque(), 0)

        # Drop skipped history entries.
        for _ in xrange(state.index):
            view.erase_regions(state.stack.popleft())
        state.index = 0

        # Append or replace new entry as the top of the stack.
        if not replace:
            state.stack.appendleft(cls.get_state(view))

            # Drop old entries.
            while len(state.stack) > history_size:
                view.erase_regions(state.stack.pop())
        else:
            view.add_regions(state.stack[0], list(view.sel()), '')

    @classmethod
    def on_close(cls, view):
        cls.states.pop(view.id(), None)

    @classmethod
    def get_state(cls, view):
        key = 'mod_{0}'.format(cls.next_id)
        cls.next_id += 1
        view.add_regions(key, list(view.sel()), '')
        return key

    @classmethod
    def move_by(cls, view, delta):
        state = cls.states.get(view.id())
        if state is None or not state.stack:
            return

        state.index = max(0, min(state.index + delta, len(state.stack) - 1))
        regions = view.get_regions(state.stack[state.index])

        sel = view.sel()
        sel.clear()
        for region in regions:
            sel.add(region)

        if regions:
            view.show(regions[0])


class GotoLastEditCommand(TextCommand):
    def run(self, edit, delta=0):
        PositionHistoryManager.move_by(self.view, delta)
