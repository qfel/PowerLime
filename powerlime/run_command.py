from __future__ import division

import json
import re

import sublime

from functools import partial
from inspect import getargspec
from types import BuiltinMethodType, MethodType

from sublime_plugin import ApplicationCommand, TextCommand, WindowCommand, \
    application_command_classes, text_command_classes, window_command_classes


class RunCommand(object):
    @staticmethod
    def _parse_docstring(doc, max_lines):
        for i, line in enumerate(doc.split('\n')):
            line = line.strip()
            if line:
                if i == max_lines:
                    yield '...'
                    return
                yield line

    @classmethod
    def _describe_command_args(cls, func):
        spec = getargspec(func)
        args = spec.args[:]
        if isinstance(func, (MethodType, BuiltinMethodType)):
            del args[0]
        del args[0:cls.SKIP_ARGS]

        if args:
            defaults = (spec.defaults or [])[-len(args):]
        else:
            defaults = []

        desc = args[:(-len(defaults) or None)]
        if defaults:
            desc.extend('{0}={1}'.format(args[i], json.dumps(defaults[i]))
                for i in xrange(len(defaults)))
        if spec.varargs:
            desc.append('{0}..'.format(spec.varargs))
        if spec.keywords:
            desc.append('[{0}]'.format(spec.keywords))
        return ', '.join(desc)

    @classmethod
    def _generate_doc(cls, func):
        desc = cls._describe_command_args(func)
        if desc:
            return ['Arguments: ' + desc]
        else:
            return ['This command takes no arguments']

    @classmethod
    def _command_info(cls, cmd_cls):
        SUFFIX = 'Command'

        info = cmd_cls.__name__
        if info.endswith(SUFFIX):
            info = info[:-len(SUFFIX)]

        info = [re.sub(r'([a-z])([A-Z])', r'\1_\2', info).lower()]
        if cmd_cls.__doc__ is not None:
            argdesc = cls._describe_command_args(cmd_cls.run)
            if argdesc:
                info.append('Arguments: ' + argdesc)
                max_lines = 2
            else:
                max_lines = 3
            info.extend(cls._parse_docstring(cmd_cls.__doc__, max_lines))
        else:
            info.extend(cls._generate_doc(cmd_cls.run))
        return info

    def _handle_command(self, commands, index):
        if index == -1:
            return

        cmd = commands[index][0]
        run = self.COMMANDS[index].run
        argdesc = self._describe_command_args(run)
        if argdesc:
            self.get_window().show_input_panel(argdesc + ':', '',
                partial(self._handle_complex_command, cmd, run), None, None)
        else:
            self.get_object().run_command(cmd)

    def _handle_complex_command(self, cmd, run, args):
        args = args.strip()
        if args:
            try:
                raw_args = json.loads('[{0}]'.format(args))
            except Exception as e:
                sublime.error_message(unicode(e))
                return

            args = {}
            spec = getargspec(run)
            skip_args = isinstance(run, (MethodType, BuiltinMethodType)) + \
                self.SKIP_ARGS

            i = 0
            while skip_args + i < len(spec.args):
                if i >= len(raw_args):
                    sublime.error_message('Value for {0} is required'.format(
                        spec.args[skip_args + i]))
                    return
                args[spec.args[skip_args + i]] = raw_args[i]
                i += 1

            if i < len(raw_args):
                if not spec.varargs:
                    sublime.error_message('Too many arguments')
                    return
                args[spec.varargs] = raw_args[i:]
        else:
            args = None
        self.get_object().run_command(cmd, args)

    def run(self):
        commands = [self._command_info(cls) for cls in self.COMMANDS]
        self.get_window().show_quick_panel(commands,
            partial(self._handle_command, commands))


class RunTextCommandCommand(RunCommand, TextCommand):
    COMMANDS = text_command_classes
    SKIP_ARGS = 1

    def get_window(self):
        return self.view.window()

    def get_object(self):
        return self.view

    def run(self, edit):
        RunCommand.run(self)


class RunWindowCommandCommand(RunCommand, WindowCommand):
    COMMANDS = window_command_classes
    SKIP_ARGS = 0

    def get_window(self):
        return self.window

    def get_object(self):
        return self.window


class RunApplicationCommandCommand(RunCommand, ApplicationCommand):
    COMMANDS = application_command_classes
    SKIP_ARGS = 0

    def get_window(self):
        return sublime.active_window()

    def get_object(self):
        return sublime
