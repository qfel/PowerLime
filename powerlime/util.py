import cPickle as pickle
import os
import os.path

from Queue import Empty, Queue
from functools import partial
from subprocess import PIPE, Popen
from threading import Lock, Thread

from sublime import View
from sublime_plugin import TextCommand

PICKLE_PROTOCOL = 2


class ExternalCallError(Exception):
    pass


class FunctionProxy(object):
    def __init__(self, caller, fname):
        self.caller = caller
        self.fname = fname

    def __call__(self, *args, **kwargs):
        proc = self.caller.get_process()
        try:
            pickle.dump((self.fname, args, kwargs), proc.stdin,
                        PICKLE_PROTOCOL)
            return pickle.load(proc.stdout)
        except (IOError, EOFError, pickle.UnpicklingError):
            self.caller.reset()
            raise ExternalCallError(proc.stderr.read())


class ExternalPythonCaller(object):
    SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
        'external'))

    proc = None

    def __init__(self, module, python='python'):
        self.popen_args = {
            'args': [
                python,
                '-u',
                os.path.join(self.SCRIPTS_DIR, 'main.py'),
                module
            ],
            'stdin': PIPE,
            'stdout': PIPE,
            'stderr': PIPE
        }

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return FunctionProxy(self, name)

    def __enter__(self):
        self.popen_args = self.popen_args
        self.proc = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.proc is True:
            self.proc = None
            return False

        pickle.dump(0, self.proc.stdin, PICKLE_PROTOCOL)
        self.proc.wait()
        self.proc = None

        return False

    def get_process(self):
        if self.proc is None:
            return Popen(**self.popen_args)
        if self.proc is True:
            self.proc = Popen(**self.popen_args)
        return self.proc

    def reset(self):
        if self.proc is not None and self.proc is not True:
            self.proc.wait()
            self.proc = True


class WorkerThread(object):
    TIMEOUT = 5

    def __init__(self):
        self.thread = None
        self.queue = Queue()
        self.lock = Lock()

    def main(self):
        while True:
            try:
                f = self.queue.get(True, self.TIMEOUT)
            except Empty:
                with self.lock:
                    if self.queue.empty():
                        self.thread = None
                        break
            else:
                f()

    def execute(self, _f, *args, **kwargs):
        with self.lock:
            self.queue.put(partial(_f, *args, **kwargs))
            if self.thread is None:
                self.thread = Thread(target=self.main)
                self.thread.start()

async_worker = WorkerThread()


def get_syntax_name(view_or_settings):
    if isinstance(view_or_settings, View):
        settings = view_or_settings.settings()
    else:
        settings = view_or_settings

    return os.path.splitext(os.path.basename(settings.get(
        'syntax')))[0].lower()


def SyntaxSpecificCommand(*syntax_names):
    def is_enabled(self, **kwargs):
        return get_syntax_name(self.view) in syntax_names

    return type(
        '{0}SpecificCommand'.format(
            ''.join(syntax.capitalize() for syntax in syntax_names)
        ),
        (TextCommand, ),
        {
            'is_enabled': is_enabled
        }
    )

CxxSpecificCommand = SyntaxSpecificCommand('c', 'c++', 'objective-c',
    'objective-c++')
PythonSpecificCommand = SyntaxSpecificCommand('python')
HaskellSpecificCommand = SyntaxSpecificCommand('haskell')
