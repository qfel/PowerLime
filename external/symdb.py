import ast
import os
import os.path

from sqlite3 import connect as sqlite_connect
from sys import argv, stdout


class SymbolDatabase(object):
    def __init__(self, path):
        self.db = sqlite_connect(path)
        self.cur = self.db.cursor()
        self.cur.executescript('''
            CREATE TABLE IF NOT EXISTS symbols (
                file_id INTEGEER,
                symbol TEXT NOT NULL,
                scope TEXT NOT NULL,
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

    def add(self, symbol, scope, path, row, col):
        self.cur.execute('''
            INSERT INTO symbols(file_id, symbol, scope, row, col)
            VALUES(
                (SELECT rowid FROM files WHERE path = :path),
                :symbol, :scope, :row, :col
            )
        ''', locals())

    def clear_file(self, name):
        self.cur.execute('''
            DELETE FROM symbols WHERE
                file_id = (SELECT rowid FROM files WHERE path = :name)
        ''', locals())

    def update_file_time(self, path, time):
        self.cur.execute('''
            SELECT timestamp FROM files WHERE path = :path
        ''', locals())
        row = self.cur.fetchone()
        if row:
            if row[0] != time:
                self.cur.execute('''
                    UPDATE files SET timestamp = ? WHERE path = ?
                ''', (time, path))
                return True
            else:
                return False
        else:
            self.cur.execute('''
                INSERT INTO files VALUES(?, ?)
            ''', (path, time))
            return True

    def commit(self):
        self.db.commit()

    def _generate_query_results(self):
        for row in self.cur:
            yield {
                'symbol': row[0],
                'scope': row[1],
                'row': row[2],
                'col': row[3],
                'file': row[4]
            }

    def occurrences(self, symbol, scope):
        self.cur.execute('''
            SELECT s.symbol, s.scope, s.row, s.col, f.path
            FROM symbols s, files f
            WHERE
                s.file_id = f.rowid AND
                s.symbol = :symbol AND
                s.scope GLOB :scope
            ORDER BY s.symbol, f.path, s.row
        ''', locals())
        return self._generate_query_results()

    def all(self):
        self.cur.execute('''
            SELECT s.symbol, s.scope, s.row, s.col, f.path
            FROM symbols s, files f
            WHERE
                s.file_id = f.rowid
            ORDER BY s.symbol, f.path, s.row
        ''')
        return self._generate_query_results()


class SymbolExtractor(ast.NodeVisitor):
    def __init__(self, db, path):
        self.path = path
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
        except (IndexError, AttributeError) as e:
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
        self.db.add(name, '.'.join(self.scope), self.path, node.lineno - 1,
            node.col_offset)


def set_db(path):
    global db
    db = SymbolDatabase(path)


def process_file(path, force=False):
    path = os.path.normcase(os.path.normpath(path))
    if db.update_file_time(path, os.stat(path).st_mtime) or force:
        db.clear_file(path)
        SymbolExtractor(db, path).visit(ast.parse(open(path).read(), path))
        db.commit()
        return True
    else:
        return False


def query_occurrences(symbol, scope='*'):
    return list(db.occurrences(symbol, scope))


def query_all():
    return list(db.all())


def main():
    WIDTH = 50
    set_db(argv[1])
    for root in argv[2:]:
        for root, dirs, files in os.walk(root):
            for file_name in files:
                if file_name.endswith('.py'):
                    stdout.write('{}...'.format(file_name))
                    stdout.flush()
                    path = os.path.abspath(os.path.join(root, file_name))
                    if process_file(path):
                        msg = 'OK'
                    else:
                        msg = 'Skipped'
                    stdout.write('{:>{}}\n'.format(msg,
                        max(0, WIDTH - len(file_name))))


if __name__ == '__main__':
    main()
