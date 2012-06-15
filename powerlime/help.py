from __future__ import division

import re

import sublime

from functools import partial
from string import whitespace
from subprocess import PIPE, Popen
from urllib import urlencode
from urlparse import SplitResult, parse_qs, urlsplit, urlunsplit

from sublime_plugin import TextCommand

from powerlime.util import ExternalPythonCaller


class SelectionCommand(TextCommand):
    PROMPT = 'selection'

    def run(self, edit, **kwargs):
        settings = self.view.settings()
        sel_auto_select = settings.get('sel_auto_select', True)
        sel_auto_query = settings.get('sel_auto_query', True)
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
                    if sel_auto_query:
                        return self.query_input(sel, kwargs)
                    elif not sel_always_query:
                        return sublime.error_message('Nothing to autoselect')
        else:
            sel = self.view.substr(sel)

        if sel_always_query:
            self.query_input(sel, kwargs)
        else:
            self.handle(sel, **kwargs)

    def query_input(self, text, kwargs):
        view = self.view.window().show_input_panel(self.PROMPT + ': ', text,
            partial(self.handle, **kwargs), None, None)
        sel = view.sel()
        sel.clear()
        sel.add(sublime.Region(0, len(text)))


class PyDocHelpCommand(SelectionCommand):
    ''' Display internal Python help index '''

    PROMPT = 'symbol'

    TYPES = {
        'att': ('attribute', r'\(.* attribute\)$'),
        'met': ('method', r'\(.* method\)$'),
        'mod': ('module', r'\(module .*\)$'),
        'cls': ('class', r'\((?:class in .*|built-in class)\)$'),
        'fun': ('function', r'\(in module .*\)$'),
        '?':   ('???', r'x^')
    }

    parseindex = ExternalPythonCaller()

    def handle(self, text):
        self.symbol_format = self.view.settings().get('pydoc_symbol_format',
            '{0} - {1}')

        index = [
            (sym, typ)
            for sym, typ
            in self.get_index().iteritems()
            if text in sym
        ]
        if not index:
            index = list(self.get_index().iteritems())

        if len(index) > 1:
            def on_select(i):
                if i != -1:
                    self.show_doc(index[i][0])

            def sym_key((sym, typ)):
                return sym.count('.'), sym, typ

            items = []
            index.sort(key=sym_key)
            for sym, typ in index:
                items.append(self.get_symbol_item(sym, typ))
            self.view.window().show_quick_panel(items, on_select,
                sublime.MONOSPACE_FONT)
        else:
            self.show_doc(index[0][0])

    def get_index(self):
        try:
            return PyDocHelpCommand.index
        except AttributeError:
            pass

        settings = self.view.settings()

        path = settings.get('pydoc_parsed_index')
        if path is not None:
            try:
                index = self.load_index(path)
            except IOError:
                pass
            else:
                print 'Loaded {0}'.format(path)
                PyDocHelpCommand.index = index
                return index

        html_path = settings.get('pydoc_html_index',
            '/usr/share/doc/python2.7/html/genindex-all.html')
        index = self.gen_index(html_path)
        print 'Parsed {0}'.format(html_path)
        PyDocHelpCommand.index = index

        with open(path, 'w') as out:
            for sym, typ in index.iteritems():
                out.write('{0}:{1}\n'.format(sym, typ))
        print 'Written {0}'.format(path)

        return index

    def gen_index(self, html_path):
        index = {}
        for href, name in self.parseindex('parseindex', html_path):
            sym = href.split('#', 1)[1]
            if re.match(r'index-\d+$', sym):
                continue
            for typ, (_, regex) in self.TYPES.iteritems():
                if re.search(regex, name):
                    index[sym] = typ
        return index

    def load_index(self, file_name):
        index = {}
        for line in open(file_name):
            sym, typ = line.rstrip('\n').split(':', 1)
            assert sym not in index
            index[sym] = typ
        return index

    def get_symbol_item(self, sym, typ):
        if self.symbol_format is None:
            return [sym, self.TYPES[typ][0]]
        else:
            return self.symbol_format.format(sym, self.TYPES[typ][0])

    # Rendering help

    def show_doc(self, sym):
        doc = self.get_doc(sym)
        if doc is None:
            return sublime.error_message('Internal help system error')

        win = sublime.active_window()
        output = win.new_file()

        edit = output.begin_edit()
        output.erase(edit, sublime.Region(0, output.size()))
        output.insert(edit, 0, doc)
        output.end_edit(edit)

        output.set_scratch(True)
        output.set_name('Help on ' + sym)
        output.set_read_only(True)
        sel = output.sel()
        sel.clear()
        sel.add(sublime.Region(0))

        settings = output.settings()
        settings.set('rulers', [])
        settings.set('line_numbers', False)
        settings.set('spell_check', False)
        settings.set('gutter', False)

    def get_doc(self, sym):
        try:
            proc = Popen(['pydoc', sym], stdout=PIPE)
        except OSError:
            return None
        output = proc.stdout.read()
        if proc.wait() != 0:
            return None
        return output


class HoogleCommand(SelectionCommand):
    PROMPT = 'hoogle query'

    hoogle = ExternalPythonCaller(timeout=5000)

    @staticmethod
    def add_query_args(url, args):
        url = urlsplit(url)._asdict()
        query = parse_qs(url['query'])
        query.update(args)
        url['query'] = urlencode(query)
        return urlunsplit(SplitResult(**url))

    def handle(self, query, internal=True):
        url = self.view.settings().get('hoogle_url',
            'http://www.haskell.org/hoogle/')
        url = self.add_query_args(url, {'hoogle': query})
        results = self.hoogle('hoogle.query_index', url)
        if results is not None:
            def on_select(index):
                if index == -1:
                    return

                if internal:
                    doc = self.hoogle('hoogle.query_details',
                        results[index]['url'])
                    if doc is None:
                        return
                    output = win.get_output_panel('hoogle')
                    output.set_read_only(False)
                    edit = output.begin_edit()
                    output.erase(edit, sublime.Region(0, output.size()))
                    output.insert(edit, 0, doc)
                    output.end_edit(edit)
                    output.set_read_only(True)
                    win.run_command('show_panel',
                        {'panel': 'output.hoogle'})
                else:
                    win.run_command('open_url', {
                        'url': results[index]['url']
                    })

            win = self.view.window()
            win.show_quick_panel(
                [[res['name'], res['loc'], res['url']] for res in results],
                on_select
            )
