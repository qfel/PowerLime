import cPickle as pickle

from importlib import import_module
from sys import argv, stdin, stdout

PICKLE_PROTOCOL = 2


def main():
    if len(argv) != 2:
        raise ValueError('Need exactly 1 argument (module)')

    module = import_module(argv[1])

    while True:
        cmd = pickle.load(stdin)
        if isinstance(cmd, tuple):
            handler = getattr(module, cmd[0])
            pickle.dump(handler(*cmd[1], **cmd[2]), stdout, PICKLE_PROTOCOL)
        else:
            return

if __name__ == '__main__':
    main()
