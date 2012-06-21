from powerlime.help.python import *
from powerlime.help.haskell import *
from powerlime.misc import *
from powerlime.format.python import *
from powerlime.run_command import *


class ReloadPowerLimeCommand(ApplicationCommand):
    DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    def run(self):
        from sys import modules
        from os import getcwd, chdir
        from sublime_plugin import reload_plugin

        names = (
            name for name in modules
            if name.startswith('powerlime.') or name == 'powerlime'
        )
        names = sorted(names, key=lambda name: name.count('.'), reverse=True)
        prev_dir = getcwd()
        try:
            chdir(self.DIR)
            for name in names:
                module = modules.get(name)
                if module is not None:
                    reload(module)
            reload_plugin(os.path.abspath('PowerLime.py'))
        finally:
            chdir(prev_dir)
