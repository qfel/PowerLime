import cPickle as pickle

from importlib import import_module
from sys import argv, stdin, stdout


def main():
    if len(argv) != 2:
        raise ValueError('Need exactly 1 argument (command path)')
    if '.' not in argv[1]:
        module = argv[1]
        handler = 'main'
    else:
        module, handler = argv[1].rsplit('.', 1)

    module = import_module(module)
    handler = getattr(module, handler)

    args, kwargs = pickle.load(stdin)
    pickle.dump(handler(*args, **kwargs), stdout, 2)

if __name__ == '__main__':
    main()
