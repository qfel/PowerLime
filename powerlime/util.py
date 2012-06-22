import cPickle as pickle
import os
import os.path

from Queue import Empty, Queue
from subprocess import PIPE, Popen
from threading import Lock, Thread

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
            pickle.dump((self.fname, args, kwargs), proc.stdin, PICKLE_PROTOCOL)
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

    def execute(self, f):
        with self.lock:
            self.queue.put(f)
            if self.thread is None:
                self.thread = Thread(target=self.main)
                self.thread.start()

async_worker = WorkerThread()
