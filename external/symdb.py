import ast
import os
import os.path

from sqlite3 import connect as sqlite_connect


class SymbolDatabase(object):
    def __init__(self, path):
        self.db = sqlite_connect(path)
        self.cur = self.db.cursor()
        self.cur.executescript('''
            CREATE TABLE IF NOT EXISTS symbols (
                file_id INTEGEER,
                symbol TEXT NOT NULL,
                scope TEXT NOT NULL,
                package TEXT NOT NULL,
                row INTEGER NOT NULL,
                col INTEGER NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(rowid)
            );

            CREATE TABLE IF NOT EXISTS files (
                path TEXT NOT NULL UNIQUE,
                timestamp REAL NOT NULL
            );
        ''')
        self.db.commit()

    def add(self, symbol, scope, package, path, row, col):
        self.cur.execute('''
            INSERT INTO symbols(file_id, symbol, scope, package, row, col)
            VALUES(
                (SELECT rowid FROM files WHERE path = :path),
                :symbol, :scope, :package, :row, :col
            )
        ''', locals())

    def clear_file(self, name):
        self.cur.execute('''
            DELETE FROM symbols WHERE
                file_id = (SELECT rowid FROM files WHERE path = :name)
        ''', locals())

    def update_file_time(self, path, time):
        args = locals()
        self.cur.execute('''
            SELECT timestamp FROM files WHERE path = :path
        ''', args)
        row = self.cur.fetchone()
        if row:
            if row[0] != time:
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

    def _generate_query_results(self):
        for row in self.cur:
            yield {
                'symbol': row[0],
                'scope': row[1],
                'package': row[2],
                'row': row[3],
                'col': row[4],
                'file': row[5]
            }

    def occurrences(self, symbol, scope, package):
        self.cur.execute('''
            SELECT s.symbol, s.scope, s.package, s.row, s.col, f.path
            FROM symbols s, files f
            WHERE
                s.file_id = f.rowid AND
                s.symbol = :symbol AND
                s.scope GLOB :scope AND
                s.package GLOB :package
            ORDER BY s.symbol, f.path, s.row
        ''', locals())
        return self._generate_query_results()

    def all(self):
        self.cur.execute('''
            SELECT s.symbol, s.scope, s.package, s.row, s.col, f.path
            FROM symbols s, files f
            WHERE
                s.file_id = f.rowid
            ORDER BY s.symbol, f.path, s.row
        ''')
        return self._generate_query_results()


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
        try:
            self.this = node.args.args[0].id
        except (IndexError, AttributeError):
            pass
        else:
            if self.this in ('cls', 'self'):
                self.generic_visit(node)
            self.this = None

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


def set_db(path):
    global db
    db = SymbolDatabase(path)


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
    if db.update_file_time(path, os.stat(path).st_mtime) or force:
        db.clear_file(path)
        SymbolExtractor(db, path, get_package(path)).visit(ast.parse(
            open(path).read(), path))
        db.commit()
        return True
    else:
        return False


def query_occurrences(symbol, scope='*', package='*'):
    return list(db.occurrences(symbol, scope, package))


def query_all():
    return list(db.all())
