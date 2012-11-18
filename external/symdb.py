import ast
import os
import os.path

from sqlite3 import connect as sqlite_connect


class SymbolDatabase(object):
    def __init__(self, path, others):
        self.db = sqlite_connect(path)
        self.cur = self.db.cursor()
        self.cur.executescript('''
            CREATE TABLE IF NOT EXISTS symbols (
                file_id INTEGER REFERENCES files(id),
                symbol TEXT NOT NULL,  -- Symbol name, valid Python identifier.
                scope TEXT NOT NULL,   -- Scope inside a file (eg. class name).
                package TEXT NOT NULL, -- Package name (eg. "os.path").
                row INTEGER NOT NULL,
                col INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS symbols_symbol ON symbols(symbol);

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                timestamp REAL NOT NULL    -- Last modification time.
            );
        ''')

        self.db_prefixes = ['']
        for i in xrange(len(others)):
            db_name = 'db{}'.format(i)
            self.cur.execute('''
                ATTACH DATABASE ? AS ?
            ''', (others[i], db_name))
            self.db_prefixes.append('{}.'.format(db_name))

        # Performance sucks when using views.
        # self.cur.execute('CREATE TEMP VIEW all_symbols AS ' +
        #     ' UNION ALL '.join(
        #         'SELECT * FROM {prefix}symbols'.format(prefix)
        #         for prefix in self.db_prefixes
        #     )
        # )

    def add(self, symbol, scope, package, path, row, col):
        self.cur.execute('''
            INSERT INTO symbols(file_id, symbol, scope, package, row, col)
            VALUES(
                (SELECT id FROM files WHERE path = :path),
                :symbol, :scope, :package, :row, :col
            )
        ''', locals())

    def clear_file(self, name):
        self.cur.execute('''
            DELETE FROM symbols WHERE
                file_id = (SELECT id FROM files WHERE path = :name)
        ''', locals())

    def remove_other_files(self, file_paths):
        self.cur.execute('''
            CREATE TEMP TABLE file_ids (
                file_id INTEGER REFERENCES files(id)
            )
        ''')
        for file_path in file_paths:
            self.cur.execute('''
                INSERT INTO file_ids
                SELECT id
                FROM files WHERE path = :file_path
            ''', {'file_path': file_path})
        self.cur.execute('''
            DELETE FROM symbols WHERE file_id NOT IN (
                SELECT file_id FROM file_ids)
        ''')
        self.cur.execute('''
            DELETE FROM files WHERE id NOT IN (
                SELECT file_id FROM file_ids)
        ''')

    def update_file_time(self, path, time):
        args = locals()
        self.cur.execute('''
            SELECT timestamp FROM files WHERE path = :path
        ''', args)
        row = self.cur.fetchone()
        if row:
            if row[0] < time:
                self.cur.execute('''
                    UPDATE files SET timestamp = :time WHERE path = :path
                ''', args)
                return True
            else:
                return False
        else:
            self.cur.execute('''
                INSERT INTO files(path, timestamp) VALUES(:path, :time)
            ''', args)
            return True

    def commit(self):
        self.db.commit()

    def _result_row_to_dict(self, row):
        return {
            'symbol': row[0],
            'scope': row[1],
            'package': row[2],
            'row': row[3],
            'col': row[4],
            'file': row[5]
        }

    def occurrences(self, symbol, scope, package):
        for db_prefix in self.db_prefixes:
            self.cur.execute('''
                SELECT s.symbol, s.scope, s.package, s.row, s.col, f.path
                FROM {db_prefix}symbols s, {db_prefix}files f
                WHERE
                    s.file_id = f.id AND
                    s.symbol = :symbol AND
                    s.scope GLOB :scope AND
                    s.package GLOB :package
                ORDER BY s.symbol, f.path, s.row
            '''.format(db_prefix=db_prefix), locals())
            for row in self.cur:
                yield self._result_row_to_dict(row)

    def all(self):
        for db_prefix in self.db_prefixes:
            self.cur.execute('''
                SELECT s.symbol, s.scope, s.package, s.row, s.col, f.path
                FROM {db_prefix}symbols s, {db_prefix}files f
                WHERE
                    s.file_id = f.id
                ORDER BY s.symbol, f.path, s.row
            '''.format(db_prefix=db_prefix))
            for row in self.cur:
                yield self._result_row_to_dict(row)

    def indexed_files(self):
        self.cur.execute('''
            SELECT DISTINCT f.path
            FROM symbols s, files f
            WHERE s.file_id = f.id
        ''')
        return (row[0] for row in self.cur)


class SymbolExtractor(ast.NodeVisitor):
    def __init__(self, db, path, package):
        self.path = path
        self.package = package
        self.db = db
        self.scope = []
        self.this = None

    def generic_visit(self, node):
        if isinstance(node, ast.expr):
            return
        ast.NodeVisitor.generic_visit(self, node)

    def visit_FunctionDef(self, node):
        self.add_symbol(node.name, node)
        # try:
        #     self.this = node.args.args[0].id
        # except (IndexError, AttributeError):
        #     pass
        # else:
        #     if self.this in ('cls', 'self'):
        #         self.generic_visit(node)
        #     self.this = None

    def visit_ClassDef(self, node):
        if self.this is None:
            self.add_symbol(node.name, node)
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

    def visit_Assign(self, node):
        self.process_assign(node.targets)

    def process_assign(self, targets):
        for target in targets:
            if isinstance(target, (ast.Tuple, ast.List)):
                self.process_assign(target.elts)
            elif isinstance(target, ast.Attribute):
                if isinstance(target.value, ast.Name) and \
                        target.value.id == self.this:
                    self.add_symbol(target.attr, target)
            elif isinstance(target, ast.Name) and self.this is None:
                self.add_symbol(target.id, target)

    def add_symbol(self, name, node):
        self.db.add(name, '.'.join(self.scope), self.package, self.path,
            node.lineno - 1, node.col_offset)


db = None


def set_db(paths):
    global db
    db = SymbolDatabase(paths[0], paths[1:])


def get_package(path):
    assert path.endswith('.py')
    path = path[:-3]
    path, module = os.path.split(path)
    package = [module]
    while True:
        new_path, module = os.path.split(path)
        if not os.path.isfile(os.path.join(path, '__init__.py')):
            break
        package.append(module)
        if new_path == path:
            break
        path = new_path
    return '.'.join(reversed(package))


def process_file(path, force=False):
    path = os.path.normcase(os.path.normpath(path))
    if db.update_file_time(path, os.path.getmtime(path)) or force:
        db.clear_file(path)
        try:
            file_ast = ast.parse(open(path).read(), path)
        except:
            return False
        SymbolExtractor(db, path, get_package(path)).visit(file_ast)
        return True
    else:
        return False


def remove_other_files(file_paths):
    db.remove_other_files(file_paths)


def query_occurrences(symbol, scope='*', package='*'):
    return list(db.occurrences(symbol, scope, package))


def query_all():
    return list(db.all())


def commit():
    db.commit()
