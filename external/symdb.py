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

    def add(self, symbol, path, row, col):
        self.cur.execute('''
            INSERT INTO symbols VALUES((SELECT rowid FROM files WHERE path = ?) , ?, ?, ?)
        ''', (path, symbol, row, col))

    def clear_file(self, name):
        self.cur.execute('''
            DELETE FROM symbols WHERE
                file_id = (SELECT rowid FROM files WHERE path = ?)
        ''', (name,))

    def update_file_time(self, path, time):
        self.cur.execute('''
            SELECT timestamp FROM files WHERE path = ?
        ''', (path,))
        row = self.cur.fetchone()
        if row:
            if row[0] < time:
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

    def symbols_like(self, pattern):
        self.cur.execute('''
            SELECT s.symbol, s.row, s.col, f.path
            FROM symbols s, files f
            WHERE
                s.file_id = f.rowid AND
                s.symbol GLOB ?
            ORDER BY s.symbol, f.path, s.row
        ''', (pattern,))
        for row in self.cur:
            yield {
                'symbol': row[0],
                'row': row[1],
                'col': row[2],
                'file': row[3]
            }


class SymbolExtractor(ast.NodeVisitor):
    def __init__(self, db, path):
        self.path = path
        self.db = db

    def generic_visit(self, node):
        if isinstance(node, ast.expr):
            return
        ast.NodeVisitor.generic_visit(self, node)

    def visit_FunctionDef(self, node):
        self.db.add(node.name, self.path, node.lineno - 1, node.col_offset)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.db.add(node.name, self.path, node.lineno - 1, node.col_offset)
        self.generic_visit(node)


def process_file(db, path, force=False):
    if isinstance(db, basestring):
        db = SymbolDatabase(db)

    path = os.path.normcase(os.path.normpath(path))
    if db.update_file_time(path, os.stat(path).st_mtime) or force:
        db.clear_file(path)
        SymbolExtractor(db, path).visit(ast.parse(open(path).read(), path))
        db.commit()
        return True
    else:
        return False


def query_symbol_like(db, pattern):
    return list(SymbolDatabase(db).symbols_like(pattern))


def main():
    WIDTH = 50
    db = SymbolDatabase(argv[1])
    for root in argv[2:]:
        for root, dirs, files in os.walk(root):
            for file_name in files:
                if file_name.endswith('.py'):
                    stdout.write('{}...'.format(file_name))
                    stdout.flush()
                    path = os.path.abspath(os.path.join(root, file_name))
                    if process_file(db, path):
                        msg = 'OK'
                    else:
                        msg = 'Skipped'
                    stdout.write('{:>{}}\n'.format(msg,
                        max(0, WIDTH - len(file_name))))


if __name__ == '__main__':
    main()
