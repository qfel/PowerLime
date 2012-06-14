import cPickle as pickle
import os
import os.path

import sublime

from functools import partial
from subprocess import CalledProcessError, PIPE, Popen
from threading import Thread


class ExternalPythonCaller(object):
    def __init__(self, python='python', timeout=None):
        self.popen_args = {
            'args': [
                python,
                '-u',
                os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                    'external', 'main.py')),
                None
            ],
            'stdin': PIPE,
            'stdout': PIPE,
            'stderr': PIPE
        }
        self.timeout = timeout
        self.proc = None

    def __call__(self, _path, *args, **kwargs):
        proc = self.proc
        if proc is not None:
            self.try_kill(proc)

        self.popen_args['args'][-1] = _path
        self.proc = Popen(**self.popen_args)
        if self.timeout is not None:
            sublime.set_timeout(
                partial(self.try_kill, self.proc),
                self.timeout
            )

        argp = args, kwargs
        callback = kwargs.pop('_callback', None)
        if callback:
            Thread(
                target=self.async_communicate,
                args=(self.proc, argp, callback)
            ).start()
        else:
            return self.communicate(self.proc, argp)

    @staticmethod
    def try_kill(proc):
        try:
            proc.kill()
        except OSError:
            pass

    def async_communicate(self, proc, argp, callback):
        callback(self.communicate(self.proc, argp))

    def communicate(self, proc, argp):
        out, err = proc.communicate(pickle.dumps(argp))

        ret = proc.wait()
        self.proc = None
        if ret != 0:
            print 'Subprocess exited with error {0}:\n{1}'.format(ret, err)
            raise CalledProcessError(ret, 'python')
        else:
            return pickle.loads(out)
