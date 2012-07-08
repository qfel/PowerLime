import ast

from itertools import groupby

from sublime_plugin import TextCommand

from powerlime.util import PythonSpecificCommand


class PythonImportFormatter(object):
    ''' Sorts Python imports '''

    def __init__(self, wrap_at=None, indent=None, min_group_size=None):
        self.wrap_at = wrap_at
        self.indent = indent or ' '
        self.min_group_size = min_group_size or float('inf')

    def _break_lines(self):
        if self.wrap_at is None:
            return

        output = []
        for line in self._output:
            while len(line) > self.wrap_at:
                i = self.wrap_at - 2
                while i > 0:
                    if line[i] == ' ':
                        output.append(line[:i] + ' \\')
                        line = self.indent + line[i + 1:]
                        break
                    i -= 1
                else:
                    break
            output.append(line)
        self._output = output

    def _indent(self, cols):
        n = len(self.indent)
        return (self.indent * ((cols + n - 1) // n))[:cols]

    def _format_aliases(self, aliases):
        return u', '.join(
            alias.name if alias.asname is None else
                u'{0} as {1}'.format(alias.name, alias.asname)
            for alias in aliases
        )

    def _format_import(self, imp):
        return u'{0}import {1}'.format(
            self._indent(imp.col_offset),
            self._format_aliases(imp.names)
        )

    def _format_from_import(self, imp):
        return u'{0}from {1} import {2}'.format(
            self._indent(imp.col_offset),
            '.' * imp.level + (imp.module or ''),
            self._format_aliases(imp.names)
        )

    def _sort_aliases(self, aliases):
        aliases.sort(key=lambda alias: alias.name)

    def _sort_imports(self, imports):
        for imp in imports:
            self._sort_aliases(imp.names)
        imports.sort(key=lambda imp: imp.names[0].name)

    def _sort_from_imports(self, imports):
        for imp in imports:
            self._sort_aliases(imp.names)
        imports.sort(key=lambda imp: (imp.level, imp.module))

    def _import_key(self, imp):
        if len(imp.names) == 1:
            return imp.names[0].name.split('.', 1)[0]
        else:
            return None

    def _from_import_key(self, imp):
        return imp.level, (imp.module or '').split('.', 1)[0]

    def _output_formatted(self, imports, formatter, keyfunc):
        def flush():
            if group_size >= self.min_group_size and group_start is not None:
                self._output.insert(group_start, '')

        key = None
        group_size = 0
        for imp in imports:
            new_key = keyfunc(imp)
            if key != new_key:
                flush()
                key = new_key
                if group_size >= self.min_group_size:
                    self._output.append('')
                    group_start = None
                else:
                    group_start = len(self._output)
                group_size = 1
            else:
                group_size += 1
            self._output.append(formatter(imp))
        flush()

    def format(self, src):
        self._output = []
        for isspace, lines in groupby(src.split('\n'),
                lambda s: s.isspace() or not s):
            if not isspace:
                lines = list(lines)
                try:
                    src = ast.parse(u'\n'.join(lines))
                except SyntaxError:
                    self._output.extend(lines)
                    continue
                except TypeError:
                    self._output.extend(lines)
                    continue

                imports = []
                from_imports = []
                for stmt in src.body:
                    if isinstance(stmt, ast.Import):
                        imports.append(stmt)
                    elif isinstance(stmt, ast.ImportFrom):
                        from_imports.append(stmt)
                    else:
                        self._output.extend(lines)
                        break
                else:
                    self._sort_imports(imports)
                    self._sort_from_imports(from_imports)
                    self._output_formatted(imports, self._format_import,
                        self._import_key)
                    if imports and from_imports:
                        self._output.append('')
                    self._output_formatted(from_imports,
                        self._format_from_import, self._from_import_key)
            else:
                self._output.extend(lines)

        self._break_lines()
        return u'\n'.join(self._output)


class SortPythonImportsCommand(PythonSpecificCommand):
    ''' Sort Python imports '''

    def run(self, edit):
        view = self.view
        settings = view.settings()
        kwargs = {'min_group_size': settings.get('sort_py_imports_group', 2)}
        rulers = settings.get('rulers')
        if rulers is not None:
            kwargs['indent'] = ' ' * settings.get('tab_size', 4)
            kwargs['wrap_at'] = min(rulers)
        formatter = PythonImportFormatter(**kwargs)

        sel = view.sel()
        if len(sel) == 1 and sel[0].empty():
            sel = view.find_all(r'^(?:(?:import|from)\s[^\\\n]*(\\\n[^\\\n]*)*\n)+')

        for region in sel:
            region = view.line(region)
            text = view.substr(region)
            new_text = formatter.format(text)
            if text != new_text:
                view.replace(edit, region, new_text)
