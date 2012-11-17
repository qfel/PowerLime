from __future__ import division

import os
import os.path
import re

from functools import partial
from subprocess import PIPE, Popen

from sublime import MONOSPACE_FONT, Region, active_window, error_message, \
    set_timeout, status_message
from sublime_plugin import EventListener

from powerlime.help.base import SelectionCommand
from powerlime.util import ExternalPythonCaller, PythonSpecificCommand, \
    async_worker


def is_python_source_file(file_name):
    return file_name.endswith('.py') or file_name.endswith('.pyw')


class PyDocHelpCommand(SelectionCommand, PythonSpecificCommand):
    ''' Display internal Python help index '''

    PROMPT = 'symbol'

    TYPES = {
        'att': ('attribute', r'\(.* attribute\)$'),
        'met': ('method', r'\(.* method\)$'),
        'mod': ('module', r'\(module\)$'),
        'cls': ('class', r'\((?:class in .*|built-in class)\)$'),
        'fun': ('function', r'\(in module .*\)$'),
    }

    parseindex = ExternalPythonCaller('parseindex')

    def handle(self, text):
        if text.startswith('?'):
            if not self.show_doc(text[1:].strip()):
                error_message('Not found')
            return

        self.symbol_format = self.view.settings().get('pydoc_symbol_format',
            '{0} - {1}')

        index = [
            (sym, typ)
            for sym, typ
            in self.get_index().iteritems()
            if text in sym.split('.')
        ]
        if not index:
            if self.show_doc(text):
                return
            index = self.get_index().items()
        elif len(index) == 1 and index[0][0] == text and \
                self.show_doc(index[0][0]):
            return

        def on_select(i):
            if i == len(index):
                self.query_input('? ' + text, select=(2, None))
            elif i != -1:
                self.show_doc(index[i][0])

        def sym_key((sym, typ)):
            return sym.count('.'), sym, typ

        items = []
        index.sort(key=sym_key)
        for sym, typ in index:
            items.append(self.get_symbol_item(sym, typ))
        items.append('<other...>')
        self.view.window().show_quick_panel(items, on_select,
            MONOSPACE_FONT)

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
        MOD_PREFIX = 'module-'
        index = {}
        for href, name in self.parseindex.main(html_path):
            sym = href.split('#', 1)[1]
            if re.match(r'index-\d+$', sym):
                continue
            for typ, (_, regex) in self.TYPES.iteritems():
                if re.search(regex, name):
                    if typ == 'mod' and sym.startswith(MOD_PREFIX):
                        sym = sym[len(MOD_PREFIX):]
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
            error_message('Internal help system error')
            return False
        if doc.startswith('no Python documentation found for '):
            return False

        win = active_window()
        output = win.new_file()

        edit = output.begin_edit()
        output.erase(edit, Region(0, output.size()))
        output.insert(edit, 0, doc)
        output.end_edit(edit)

        output.set_scratch(True)
        output.set_name('Help on ' + sym)
        output.set_read_only(True)
        sel = output.sel()
        sel.clear()
        sel.add(Region(0))

        settings = output.settings()
        settings.set('rulers', [])
        settings.set('line_numbers', False)
        settings.set('spell_check', False)
        settings.set('gutter', False)

        return True

    def get_doc(self, sym):
        try:
            proc = Popen(['pydoc', sym], stdout=PIPE)
        except OSError:
            return None
        output = proc.stdout.read()
        if proc.wait() != 0:
            return None
        return output

symdb = ExternalPythonCaller('symdb')


def async_status_message(msg):
    set_timeout(partial(status_message, msg), 0)


def get_db_paths(settings):
    paths = settings.get('pytags_db_path', '$HOME/.pytags.db')
    if isinstance(paths, basestring):
        return [os.path.expandvars(paths)]
    else:
        return map(os.path.expandvars, paths)


def get_symbol_roots(view):
    settings = view.settings()
    symbol_roots = settings.get('pytags_roots', [])
    if settings.get('pytags_include_project_folders', True):
        symbol_roots += view.window().folders()
    return symbol_roots


class PyFindSymbolCommand(SelectionCommand, PythonSpecificCommand):
    def handle(self, text):
        db = get_db_paths(self.view.settings())

        with symdb:
            symdb.set_db(db)
            results = symdb.query_occurrences(text)
            if not results:
                results = symdb.query_all()

        if len(results) != 1:
            def on_select(i):
                if i != -1:
                    self.goto(results[i])

            self.view.window().show_quick_panel(map(self.format_result,
                                                    results),
                                                on_select)
        else:
            self.goto(results[0])

    def goto(self, result):
        view = self.view.window().open_file(result['file'])
        pos = (result['row'], result['col'])
        if view.is_loading():
            PyTagsListener.view_pos = pos
            PyTagsListener.view_id = view.id()
        else:
            PyTagsListener.goto(view, pos)

    def format_result(self, result):
        dir_name, file_name = os.path.split(result['file'])
        return ['.'.join(filter(None, (result['package'], result['scope'],
                                       result['symbol']))),
                u'{0}:{1}'.format(file_name, result['row']),
                dir_name]


class PyTagsListener(EventListener):
    view_id = None

    @staticmethod
    def index_view(view):
        def async():
            with symdb:
                symdb.set_db(get_db_paths(view.settings()))
                if symdb.process_file(view.file_name()):
                    async_status_message('Indexed ' + view.file_name())
                symdb.commit()
        async_worker.execute(async)

    @classmethod
    def on_load(cls, view):
        if is_python_source_file(view.file_name()):
            if view.settings().get('pytags_index_on_load'):
                cls.index_view(view)

        if cls.view_id is not True and view.id() != cls.view_id:
            return

        cls.goto(view, cls.view_pos)
        cls.view_id = None

    def on_post_save(self, view):
        if is_python_source_file(view.file_name()):
            if view.settings().get('pytags_index_on_save'):
                self.index_view(view)

    @staticmethod
    def goto(view, pos):
        sel = view.sel()
        sel.clear()
        sel.add(Region(view.text_point(*pos)))
        view.show(sel, True)


class PyBuildIndexCommand(PythonSpecificCommand):
    def run(self, edit, rebuild=False):
        async_worker.execute(self.async_process_files,
                             get_symbol_roots(self.view),
                             get_db_paths(self.view.settings()), rebuild)

    def async_process_files(self, symbol_roots, db_paths, rebuild):
        if rebuild:
            os.remove(db_paths[0])

        with symdb:
            symdb.set_db(db_paths)
            paths = []
            for symbol_root in symbol_roots:
                for root, dirs, files in os.walk(symbol_root):
                    for file_name in files:
                        if is_python_source_file(file_name):
                            path = os.path.abspath(os.path.join(root,
                                                                file_name))
                            paths.append(path)
                            if symdb.process_file(path, rebuild):
                                async_status_message('Indexed ' + path)
            symdb.remove_other_files(paths)
            symdb.commit()

        async_status_message('Done indexing')
