
import sublime

from functools import partial
from string import whitespace

from sublime_plugin import TextCommand


class SelectionCommand(TextCommand):
    PROMPT = 'selection'

    def run(self, edit, **kwargs):
        settings = self.view.settings()
        sel_auto_select = settings.get('sel_auto_select', True)
        sel_always_query = settings.get('sel_always_query', False)

        sel = self.view.sel()
        if len(sel) != 1:
            return sublime.error_message('Multiple selections not supported')

        sel = sel[0]
        if sel.empty():
            if sel_auto_select:
                sel = self.view.substr(self.view.word(sel))
                bad_chars = settings.get('word_separators') + whitespace
                if set(sel) <= set(bad_chars):
                    return self.query_input(sel, kwargs)
            else:
                return self.query_input('', kwargs)
        else:
            sel = self.view.substr(sel)

        if sel_always_query:
            self.query_input(sel, kwargs)
        else:
            self.handle(sel, **kwargs)

    def query_input(self, text, kwargs={}, select=(None, None)):
        view = self.view.window().show_input_panel(self.PROMPT + ': ', text,
            partial(self.handle, **kwargs), None, None)
        if select:
            sel = view.sel()
            sel.clear()
            sel.add(sublime.Region(
                0 if select[0] is None else select[0],
                len(text) if select[1] is None else select[1]
            ))
