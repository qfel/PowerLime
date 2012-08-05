import os.path
import sys
import re

from collections import namedtuple

from sublime import ENCODED_POSITION, View, error_message, load_settings, \
    status_message
from sublime_plugin import TextCommand


SymbolRef = namedtuple('SymbolRef', 'file row col pos context')


class XTagsCommand(TextCommand):
    handlers = {}

    def run(self, edit, language=None, source=None,
            types=('def', 'read', 'write')):
        view = self.view
        if language is None:
            language = get_syntax_name(view)
        tags = []
        selections = view.sel()
        for handler in self.handler.get(language, []):
            if source is None or handler.NAME == source:
                for sel in selections:
                    if sel.empty():
                        name = handler.get_symbol_name(language, view, sel.a)
                    else:
                        name = view.substr(sel)
                tags.extend(handler.find_symbol(language, name, types))

        if not tags:
            status_message('Not found: ' + name)
            return

        if len(tags) > 1:
            view.window().show_quick_panel(map(self.tag_to_item, tags),
                    lambda i: (self.open_tag(tags[i]) if i != -1 else None))
        else:
            self.open_tag(tags[0])

    def tag_to_item(self, tag):
        item = []
        if tag.context is not None:
            item.append(tag.context)
        if tag.row is not None:
            if tag.col is None:
                suffix = ':{0}'.format(tag.row)
            else:
                suffix = ':{0}:{0}'.format(tag.row, tag.col)
        else:
            suffix = '@{0}'.format(tag.pos)
        item.append(tag.file + suffix)
        return item

    def open_tag(self, tag):
        self.view.window().open_file(
            '{0}:{1}'.format(os.path.join(self.google3_path, tag.file),
                tag.row + 1),
            ENCODED_POSITION)

    @staticmethod
    def format_handler_name(name):
        SUFFIX = 'Handler'
        if name.endswith(SUFFIX):
            name = name[:-len(SUFFIX)]
        return re.sub(r'([a-z0-9])([A-Z][a-z])', r'\1_\2', name).lower()

    @classmethod
    def register_handler(cls, handler):
        for language in handler.LANGUAGES:
            cls.handlers.setdefault(language, []).append(handler)

    @classmethod
    def handler(cls, handler_cls):
        if 'NAME' not in cls.__dict__:
            cls.NAME = cls.format_handler_name(cls.__name__)
        cls.register_handler(handler_cls())
        return handler


class TagsHandler(object):
    def get_symbol_name(self, language, view, pos):
        return view.substr(view.word(pos))

    def update_index(self, path):
        pass


#@XTagsCommand.handler
class GoogleTagsHandler(TagsHandler):
    def find_symbol(self, language, name, types):
        flags = []
        if 'def' in types:
            flags.append(0)
        if 'read' in types or 'write' in types:
            flags.append(1)
        for flag in flags:
            for tag in self.gtags.find_matching_tags_exact(language, name,
                    flag):
                yield SymbolRef(file=tag.filename_, row=tag.lineno_,
                    col=None, pos=tag.offset_, context=tag.snippet_)
