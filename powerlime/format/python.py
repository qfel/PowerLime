import ast
import re

from collections import namedtuple

from sublime import Region, error_message, status_message
from sublime_plugin import EventListener

from powerlime.util import PythonSpecificCommand


IMPORT_START_RE = r'(?:from[ \t]+[\w.]+[ \t]+)?import[\ \t]+'
IMPORT_PAREN_RE = r'\([^(#)]*\)[\ \t]*'
IMPORT_ESC_RE = r'[^\\#\n]*(?:\\\n[^\\#\n]*)*'

# A block of consecutive module-level import lines.
IMPORT_RE = r'^({0}(?:{1}|{2})\n)+'.format(IMPORT_START_RE, IMPORT_PAREN_RE,
                                           IMPORT_ESC_RE)


# Catches module name in <from module import ...> statement.
FROM_IMPORT_CATCH_RE = r'^[ \t]*from[ \t]([\w.]+)[ \t]import[ \t]'


# A parsed group of imports, holding it's position within the file.
ImportGroup = namedtuple('ImportGroup', 'region imports')


def try_parse(src):
    try:
        return ast.parse(src)
    except (SyntaxError, TypeError):
        return None


class PythonImportFormatter(object):
    ''' Sorts Python imports '''

    def __init__(self, settings):
        rulers = settings.get('rulers')
        if rulers is not None:
            if settings.get('translate_tabs_to_spaces'):
                self.indent = ' '
            else:
                self.indent = '\t'
            self.indent *= settings.get('tab_size', 4)
            self.wrap_at = min(rulers)
        else:
            self.indent = ' '
            self.wrap_at = float('inf')
        self.min_group_size = settings.get('pwl_sort_py_imports_group', 2) or \
                float('inf')
        self.split_by_type = True

    def append_aliases(self, aliases, start_pos):
        pos = start_pos
        parts = self.parts
        for i, alias in enumerate(aliases):
            if alias.asname is None:
                atom = alias.name
            else:
                atom = u'{0} as {1}'.format(alias.name, alias.asname)
            if i + 1 < len(aliases):
                atom += ', '
                more = 1
            else:
                more = 0

            if pos + len(atom) + more > self.wrap_at:
                parts.append('\\\n')
                if self.indent == ' ':
                    parts.append(' ' * start_pos)
                else:
                    parts.append(self.indent)
                pos = len(parts[-1])

            parts.append(atom)
            pos += len(atom)

        parts.append('\n')
        return u', '.join(parts)

    def append_import(self, imp):
        self.parts.append('import ')
        self.append_aliases(imp.names, len(self.parts[-1]))

    def append_from_import(self, imp):
        self.parts.append('from {0} import '.format(
                '.' * imp.level + (imp.module or '')))
        self.append_aliases(imp.names, len(self.parts[-1]))

    def sort_aliases(self, aliases):
        aliases.sort(key=lambda alias: alias.name)

    def sort_imports(self, imports):
        for imp in imports:
            self.sort_aliases(imp.names)
        imports.sort(key=lambda imp: imp.names[0].name)

    def sort_from_imports(self, imports):
        for imp in imports:
            self.sort_aliases(imp.names)
        imports.sort(key=lambda imp: (imp.level, imp.module))

    def import_key(self, imp):
        if len(imp.names) == 1:
            return imp.names[0].name.split('.', 1)[0]
        else:
            return None

    def from_import_key(self, imp):
        return imp.level, (imp.module or '').split('.', 1)[0]

    def append_grouped(self, imports, appender, keyfunc):
        def flush():
            if group_size >= self.min_group_size and group_start is not None:
                self.parts.insert(group_start, '\n')

        key = None
        group_size = 0
        for imp in imports:
            new_key = keyfunc(imp)
            if key != new_key:
                flush()
                key = new_key
                if group_size >= self.min_group_size:
                    self.parts.append('\n')
                    group_start = None
                else:
                    group_start = len(self.parts)
                group_size = 1
            else:
                group_size += 1
            appender(imp)
        flush()

    def format(self, stmts):
        self.parts = []

        imports = []
        from_imports = []
        for stmt in stmts:
            if isinstance(stmt, ast.Import):
                imports.append(stmt)
            elif isinstance(stmt, ast.ImportFrom):
                from_imports.append(stmt)
            else:
                raise ValueError('Unsupported statement type')

        self.sort_imports(imports)
        self.sort_from_imports(from_imports)

        self.append_grouped(imports, self.append_import, self.import_key)
        if self.split_by_type and imports and from_imports:
            self.parts.append('\n')
        self.append_grouped(from_imports, self.append_from_import,
                            self.from_import_key)
        return u''.join(self.parts)


class SortPythonImportsCommand(PythonSpecificCommand):
    ''' Sort Python imports '''

    def run(self, edit):
        view = self.view
        formatter = PythonImportFormatter(view.settings())

        # Must be sorted.
        regions = [view.full_line(sel)
                   for sel in view.sel() if not sel.empty()]
        if not regions:
            regions.extend(view.find_all(IMPORT_RE))
        regions.reverse()

        # Since regions starts from from the furthest one, replaces do not
        # change addressing of the previous ones.
        for region in regions:
            text = view.substr(region)
            ast = try_parse(text)
            if ast is not None:
                try:
                    new_text = formatter.format(ast.body)
                except ValueError:
                    status_message('Error: selection contains non-imports')
                else:
                    if text != new_text:
                        view.replace(edit, region, new_text)


class AddPythonImportCommand(PythonSpecificCommand):
    def run(self, edit):
        view = self.view

        # Try to guess what the user wants to import.
        sel = view.sel()
        if sel:
            sel = sel[0]
            if not sel.empty():
                text = view.substr(sel)
            else:
                text = view.substr(view.word(sel))
            if not re.match(r'[a-zA-Z_]\w*$', text):
                text = ''
        else:
            text = ''

        # Ask the user for the import.
        input_view = view.window().show_input_panel('module and symbols:',
                                                    text,
                                                    self.handle_add_import,
                                                    None, None)
        sel = input_view.sel()
        sel.clear()
        sel.add(Region(0, input_view.size()))
        PythonAddImportCompletion.enable_completions(input_view, self.view)

    def handle_add_import(self, text):
        tokens = text.split()
        for token in tokens:
            if not re.match(r'[a-zA-Z_][\w.]*$', token):
                error_message('Invalid identifier: ' + token)
                return

        formatter = PythonImportFormatter(self.view.settings())
        if len(tokens) > 1:
            self.add_from_import(formatter, tokens[0], tokens[1:])
        elif tokens:
            self.add_module_import(formatter, tokens[0])

    def format_imports(self, formatter, group, imp, symbols):
        for symbol in symbols:
            imp.names.append(ast.alias(name=symbol, asname=None))
        edit = self.view.begin_edit()
        self.view.replace(edit, group.region, formatter.format(group.imports))
        self.view.end_edit(edit)

    def get_preview(self, region):
        parts = []
        text = self.view.substr(region)
        for line in text.splitlines():
            parts.extend(line.split()[:2])
            parts.append('(...)')
        return u' '.join(parts)

    def add_from_import(self, formatter, module, symbols):
        symbols = set(symbols)
        groups = []  # Groups of imports saved for user choice.

        # Search for existing import to update.
        for region in self.view.find_all(IMPORT_RE):
            imports = try_parse(self.view.substr(region))
            if not imports:
                continue

            # Whether imports contain at least one "from" type import.
            interesting_group = False
            imports = imports.body

            # Search for import from specified module.
            for imp in imports:
                if isinstance(imp, ast.ImportFrom):
                    if imp.module == module:
                        # Discard already imported symbols.
                        to_remove = []
                        for alias in imp.names:
                            if alias.asname is None and alias.name in symbols:
                                to_remove.append(alias.name)
                        symbols.difference_update(to_remove)
                        if symbols:
                            self.format_imports(formatter,
                                                ImportGroup(region=region,
                                                            imports=imports),
                                                imp, symbols)
                            if to_remove:
                                status_message('Already imported: ' +
                                               ', '.join(to_remove))
                        else:
                            status_message('Already imported')
                        return
                    interesting_group = True

            if interesting_group:
                groups.append(ImportGroup(region=region, imports=imports))

        # Need to add new "from (...)" import, possibly ask the user where.
        def add_new_import(group):
            imp = ast.ImportFrom(module=module, level=0, names=[])
            group.imports.append(imp)
            return imp

        if len(groups) > 1:
            # Let the user choose which group to add to.
            def handle_group_choice(index):
                if index != -1:
                    imp = add_new_import(groups[index])
                    self.format_imports(formatter, groups[index], imp, symbols)

            self.view.window().show_quick_panel(
                    [self.get_preview(group.region) for group in groups],
                    handle_group_choice)
        else:
            # Add import to the last group.
            if not groups:
                # No imports found, add an import at the first empty line or at
                # the top of the file.
                region = self.view.find(r'^\s*\n', 0)
                if region is None:
                    region = Region(0, 0)
                groups.append(ImportGroup(region=region, imports=[]))

            imp = add_new_import(groups[-1])
            self.format_imports(formatter, groups[-1], imp, symbols)

    # def add_module_import(self, module):
    #     groups = []
    #     for region in self.view.find_all(IMPORT_RE):
    #         imports = try_parse(self.view.substr(region))
    #         if not imports:
    #             continue
    #         interesting_group = False
    #         for imp in imports:
    #             if isinstance(imp, ast.Import):
    #                 if module in (alias.name for alias in imp.names
    #                               if alias.asname is None):
    #                     status_message('Already imported')
    #                     return
    #                 interesting_group = True

    #         if interesting_group:
    #             groups.append(ImportGroup(region=region, imports=imports))

    #     # Need to add new "from (...)" import, possibly ask the user where.
    #     if len(groups) > 1:
    #         # Let the user choose which group to add to.
    #         def handle_group_choice(index):
    #             if index != -1:
    #                 imp = ast.Import(module=module, names=[])


    #         self.view.window().show_quick_panel(
    #                 [self.view.substr(group.region) for group in groups],
    #                 handle_group_choice)


class PythonAddImportCompletion(EventListener):
    view_id = None

    @classmethod
    def on_query_completions(cls, view, prefix, locations):
        if view.id() != cls.view_id:
            return

        modules = []
        cls.src_view.find_all(FROM_IMPORT_CATCH_RE, 0, r'\1', modules)
        print modules
        return [(module, module + ' ') for module in modules]

    @classmethod
    def on_close(cls, view):
        if view.id() == cls.view_id:
            cls.view_id = None
            cls.src_view = None

    @classmethod
    def enable_completions(cls, view, src_view):
        cls.view_id = view.id()
        cls.src_view = src_view
