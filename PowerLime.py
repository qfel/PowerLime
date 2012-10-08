from powerlime.format.c import *
from powerlime.format.python import *
# from powerlime.help.haskell import *
# from powerlime.help.python import *
from powerlime.cursor import *
from powerlime.layout import *
from powerlime.misc import *
from powerlime.xtags import *


if True:
    import os.path
    import sys

    from glob import glob

    from sublime import packages_path as get_packages_path
    from sublime_plugin import reload_plugin, EventListener

    def split_path(path):
        ''' Split path into list of components. '''
        components = []
        while True:
            new_path, component = os.path.split(path)
            if new_path == path:
                components.append(new_path)
                break
            components.append(component)
            if not new_path:
                break
            path = new_path
        components.reverse()
        return components

    class ComplexPluginReloader(EventListener):
        def on_post_save(self, view):
            # Assume both paths are already absolute, only normalize the case.
            packages_path = split_path(os.path.normcase(get_packages_path()))
            file_name = split_path(os.path.normcase(view.file_name()))

            # Check if the file is inside packages directory.
            if file_name[:len(packages_path)] != packages_path:
                return

            # Ignore files placed directly in packages directory, as Sublime
            # will reload them automatically.
            if len(file_name) < len(packages_path) + 3:
                return

            # Path to the package containing saved file.
            package_path = file_name[:len(packages_path) + 1]

            # Translate file name to dot-separated module name and reload the
            # module if needed.
            relative_name = file_name[len(packages_path) + 1:]
            relative_name[-1] = os.path.splitext(relative_name[-1])[0]
            module = sys.modules.get('.'.join(relative_name))
            if module is not None:
                original_dir = os.getcwd()
                os.chdir(os.path.join(*package_path))
                try:
                    reload(module)
                finally:
                    os.chdir(original_dir)

            # The module is indirectly loaded from some package top-level
            # module, so reload them too, to see the changes in Sublime.
            package_path.append('*.py')
            for file_name in glob(os.path.join(*package_path)):
                reload_plugin(file_name)
