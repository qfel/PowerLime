import os
import os.path
import re

from itertools import chain

from sublime import LITERAL, Region, TRANSIENT, set_clipboard
from sublime_plugin import EventListener, TextCommand


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


class LastEditListener(EventListener):
    state = {}

    def on_modified(self, view):
        self.state[view.id()] = (view.viewport_position(), tuple(view.sel()))

    def on_close(self, view):
        del self.state[view.id()]


class GotoLastEditCommand(TextCommand):
    def run(self, edit, animate=True):
        state = LastEditListener.state.get(self.view.id())
        if state is not None:
            print state[0]
            self.view.set_viewport_position(state[0], animate)
            sel = self.view.sel()
            sel.clear()
            for region in state[1]:
                sel.add(region)
