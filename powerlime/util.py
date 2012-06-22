import cPickle as pickle
import os
import os.path

from subprocess import PIPE, Popen

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
            raise ExternalCallError(proc.stderr.read())


class ExternalPythonCaller(object):
    SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
        'external'))

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
        self.proc = False

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return FunctionProxy(self, name)

    def __enter__(self):
        self.begin()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.end()
        return False

    def get_process(self):
        if self.proc is True:
            self.proc = Popen(**self.popen_args)
            return self.proc
        elif self.proc is False:
            return Popen(**self.popen_args)
        else:
            return self.proc

    def begin(self):
        self.proc = True

    def end(self):
        if not isinstance(self.proc, bool):
            pickle.dump(0, self.proc.stdin, PICKLE_PROTOCOL)
            self.proc.wait()
        self.proc = False
