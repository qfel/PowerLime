import os
import os.path
import re

from collections import deque, namedtuple
from itertools import chain

from sublime import LITERAL, MONOSPACE_FONT, Region, TRANSIENT, load_settings, \
    set_clipboard
from sublime_plugin import EventListener, TextCommand, WindowCommand


class CopyCurrentPath(TextCommand):
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
    def run(self, edit):
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


class StackCommand(object):
    _state = None
    __max_size = None

    def set_max_size(self, maxlen):
        if maxlen != self.__max_size:
            self.__max_size = maxlen
            self._state = deque(self._state or [], maxlen)

    def run(self, edit=None, cmd=None, internal=None):
        self.reload_settings()
        if self._state is None:
            state = self._state = []
        else:
            state = self._state

        if cmd == 'clear':
            state.clear()
        elif cmd == 'push':
            state.append(internal or self.capture_state())
        elif cmd == 'emplace':
            if state:
                state[-1] = self.capture_state()
            else:
                state.append(self.capture_state())
        elif cmd == 'pop':
            self.restore_state(state.pop())
        elif cmd == 'apply':
            self.restore_state(state[-1])
        elif cmd == 'select_apply' and hasattr(self, 'state_to_item'):
            self.get_window().show_quick_panel(
                [self.state_to_item(entry) for entry in reversed(state)],
                lambda i: (None if i == -1
                    else self.restore_state(state[-i - 1])),
                MONOSPACE_FONT
            )
        else:
            raise ValueError('Unknown command: ' + cmd)

    def is_enabled(self, cmd):
        if cmd in ('pop', 'clear', 'apply', 'select_apply'):
            return bool(self._state)
        else:
            return True


class FilesStackCommand(StackCommand, WindowCommand):
    ViewState = namedtuple('ViewState', 'file_name selections visible_region')

    def reload_settings(self):
        settings = load_settings('Preferences.sublime-settings')
        self.set_max_size(settings.get('files_stack_size', 4))

    def capture_state(self):
        groups = []
        for group_i in xrange(self.window.num_groups()):
            group = []
            for view in self.window.views_in_group(group_i):
                group.append(self.ViewState(
                    file_name=view.file_name(),
                    selections=tuple(view.sel()),
                    visible_region=view.visible_region()))
            groups.append(group)
        return groups

    def restore_state(self, state):
        self.window.run_command('close_all')
        for group_i, group in enumerate(state):
            self.window.focus_group(group_i)
            for view in group:
                self.window.open_file(view.file_name)


class ViewportStackCommand(StackCommand, TextCommand):
    def __init__(self, view):
        TextCommand.__init__(self, view)
        ViewportPusher.states[view.id()] = self, self.capture_state()

    def reload_settings(self):
        self.set_max_size(self.view.settings().get('viewport_stack_size', 10))

    def capture_state(self):
        return (self.view.viewport_position(), tuple(self.view.sel()))

    def restore_state(self, (viewport, selections)):
        ViewportPusher.expected.add(self.view.id())
        self.view.set_viewport_position(viewport)
        sel_set = self.view.sel()
        sel_set.clear()
        for sel in selections:
            sel_set.add(sel)

    def state_to_item(self, (viewport, selections)):
        item = []
        if len(selections) > 1:
            item.append('Multiple selections')
            context = 0
        else:
            context = self.view.settings().get('viewport_stack_context', 2)
            if context > 0:
                item.append('{0} characters selected'.format(
                    sum(sel.size() for sel in selections)))

        for sel in selections:
            begin_row, begin_col = self.view.rowcol(sel.a)
            end_row, end_col = self.view.rowcol(sel.b)

            if context > 0 and begin_row > 0:
                region = Region(
                    self.view.text_point(max(begin_row - context, 0), 0),
                    self.view.text_point(begin_row, 0) - 1
                )
                lines = self.view.lines(region)
                for i, line in enumerate(lines):
                    item.append('{0}: {1}'.format(
                        begin_row - len(lines) + i + 1, self.view.substr(line)))

            if begin_row == end_row:
                item.append('{0}:{1} {2}'.format(
                    begin_row + 1,
                    begin_col + 1 if begin_col == end_col
                        else '{0}-{1}'.format(begin_col + 1, end_col + 1),
                    self.view.substr(self.view.line(sel))
                ))
            else:
                lines = self.view.lines(sel)
                for i, line in enumerate(lines):
                    if i == 0:
                        col = begin_col
                    elif i == len(lines) - 1:
                        col = end_col
                    else:
                        col = '*'
                    item.append('{0}:{1} {2}'.format(
                        begin_row + 1 + i,
                        col,
                        self.view.substr(self.view.line(sel))
                    ))

            if context > 0:
                region = Region(
                    self.view.text_point(end_row + 1, 0),
                    self.view.text_point(end_row + 1 + context, 0) - 1
                )
                if region.a < region.b:
                    for i, line in enumerate(self.view.lines(region)):
                        item.append('{0}: {1}'.format(end_row + 2 + i,
                            self.view.substr(line)))

        return item

    def get_window(self):
        return self.view.window()


class ViewportPusher(EventListener):
    class State(object):
        def __init__(self, cmd, state):
            self.cmd = cmd
            self.state = state

    states = {}
    expected = set()
    settings = load_settings('Preferences.sublime-settings')

    def on_selection_modified(self, view):
        if not self.settings.get('viewport_stack_auto'):
            return
        entry = self.states.get(view.id())
        if entry is None:
            return

        cmd, last_state = entry
        state = cmd.capture_state()
        if view.id() in self.expected:
            self.expected.remove(view.id())
        elif state[0] != last_state[0]:
            cmd.run(None, cmd='push', internal=last_state)
        self.states[view.id()] = cmd, state

    def on_close(self, view):
        self.expected.discard(view.id())
        del self.states[view.id()]
