import re

from sublime import Region
from sublime_plugin import TextCommand


class GotoBlockCommand(TextCommand):
    ''' Moves cursor to text with specified indentation with respect to its
    current position '''

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


class DeletePartCommand(TextCommand):
    ''' Delete part of a word '''

    # Taken from default Sublime settings
    WORD_SEPARATORS = "./\\()\"'-:,.;<>~!@#$%^&*|+=[]{}`~?"

    def run(self, edit, forward=True):
        view = self.view
        word_separators = view.settings().get('word_separators',
            self.WORD_SEPARATORS)
        word_separators = frozenset(word_separators)

        for sel in view.sel():
            if not sel.empty():
                continue

            line_sel = view.line(sel)
            if forward:
                part = view.substr(Region(sel.a, line_sel.b))
            else:
                part = reversed(view.substr(Region(line_sel.a, sel.a)))

            index = 0  # In case part is empty
            char_class = 0
            for index, char in enumerate(part):
                if char.isspace() or char in word_separators:
                    break
                if char.isupper():
                    if forward and char_class == -1:
                        break
                    char_class = 1
                elif char.islower():
                    if not forward and char_class == 1:
                        break
                    char_class = -1
                elif char.isdigit():
                    char_class = 0
                else:
                    break

            if index > 0:
                view.erase(edit,
                    Region(sel.a, sel.a + index)
                    if forward else
                    Region(sel.a - index, sel.a)
                )
