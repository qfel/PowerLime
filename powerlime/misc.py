import os
import os.path
import re

from collections import namedtuple
from itertools import chain

from sublime import LITERAL, Region, TRANSIENT, set_clipboard
from sublime_plugin import TextCommand, WindowCommand


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
                    r'\b{0}\b'.format(
                        re.escape(
                            view.substr(
                                view.word(
                                    single_sel)))),
                    0
                )
            else:
                regions = self.find_iter(
                    visible_region,
                    view.substr(single_sel),
                    LITERAL
                )

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
                    sel.a - line.a
                )
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
                            break
                    else:
                        continue
                else:
                    full_name = file_name
                window.open_file(full_name, flags)
                break

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
    def run(self, edit, selector, unfold=False, preserve_newlines=True):
        regions = self.view.find_by_selector(selector)
        if unfold:
            self.view.unfold(regions)
        else:
            if preserve_newlines:
                for i, region in enumerate(regions):
                    if not region.empty() and \
                            self.view.substr(region.b - 1) == '\n':
                        regions[i] = Region(region.a, region.b - 1)
            self.view.fold(regions)


class FilesStackCommand(WindowCommand):
    ViewState = namedtuple('ViewState', 'file_name selections visible_region')

    def __init__(self, *args, **kwargs):
        WindowCommand.__init__(self, *args, **kwargs)
        self.state = []

    def run(self, cmd):
        if cmd == 'clear':
            self.state.clear()
        elif cmd == 'push':
            self.state.append(self.capture_state())
        elif cmd == 'emplace':
            if self.state:
                self.state[-1] = self.capture_state()
            else:
                self.state.append(self.capture_state())
        elif cmd == 'pop':
            self.restore_state(self.state.pop())
        elif cmd == 'apply':
            self.restore_state(self.state[-1])
        else:
            raise ValueError('Unknown command: ' + cmd)

    def is_enabled(self, cmd):
        if cmd in ('pop', 'clear', 'apply'):
            return bool(self.state)
        else:
            return True

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
