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

    def run(self, edit, language=None, types=('def', 'read', 'write'),
            sources=None):
        view = self.view
        if language is None:
            language = get_syntax_name(view)
        handler_count = 0
        matches = []
        selections = view.sel()
        for handler in self.handler.get(language, []):
            if handler.NAME in sources:
                for sel in selections:
                    if sel.empty():
                        name = handler.get_symbol_name(language, view,
                            sel.a)
                    else:
                        name = view.substr(sel)
                matches.extend(handler.find_symbol(language, name, types))
                handler_count += 1

        if not matches:
            status_message('Not found: ' + name)
            return

        if len(matches) > 1:
            if handler_count > 1:
                self.remove_duplicates(matches)
            view.window().show_quick_panel(map(self.tag_to_item, matches),
                    lambda i: (self.open_tag(matches[i]) if i != -1 else None))
        else:
            self.open_tag(matches[0])

    def remove_duplicates(self, tags):
        for i in xrange(len(tags) - 1, 0, -1):
            if tags[i].file == tags[i - 1].file and tag

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
    def get_symbol_name(self, settings, language, view, pos):
        return view.substr(view.word(pos))


@XTagsCommand.handler
class GoogleTagsHandler(TagsHandler):
    def find_symbol(self, settings, language, name, types):
        flags = []
        if 'def' in types:
            flags.append(0)
        if 'read' in types or 'write' in types:
            flags.append(1)
        for flag in flags:
            for match in self.gtags.find_matching_tags_exact(language, name,
                    flag)):
                yield SymbolRef(file=match.filename_, row=match.lineno_,
                    col=None, pos=match.offset_, context=match.snippet_)


class GoogleTagsCommand(TextCommand):
    gtags = None
    google3_path = None
    settings = load_settings('Preferences.sublime-settings')

    @classmethod
    def on_google3_set(cls):
        google3_path = cls.settings.get('google3_path')
        if google3_path == cls.google3_path:
            return

        cls.gtags = None
        cls.google3_path = google3_path
        if google3_path is None:
            return

        # Unload previously loaded gtags version
        if 'gtags' in sys.modules:
            del sys.modules['gtags']
        if 'gtags_google' in sys.modules:
            del sys.modules['gtags_google']

        # Load gtags modules
        gtags_path = os.path.join(google3_path, 'tools', 'tags')
        sys.path.append(gtags_path)
        try:
            import gtags
            import gtags_google
        except ImportError as e:
            error_message(
                'google3_path is set to "{0}" but gtags module(s) not found: {1}\n'
                'Make sure you have run prodaccess.'.format(google3_path, e)
            )
            return
        finally:
            sys.path.remove(gtags_path)

        gtags_google.define_servers('google3')
        gtags.connection_manager.use_mixer = True

        cls.gtags = gtags

    def run(self, edit, language=None, references=False):
        if language is None:
            language = get_syntax_name(self.view)

        sel = self.view.sel()
        for sel in sel:
            if sel.empty():
                sel = self.view.word(sel)
            tag = self.view.substr(sel)
            tags = self.gtags.find_matching_tags_exact(language, str(tag),
                1 if references else 0)
            if not tags:
                status_message('Not found: ' + tag)
                return

            if len(tags) > 1:
                self.view.window().show_quick_panel(self.tags_to_items(tags),
                    lambda i: (self.open_tag(tags[i]) if i != -1 else None))
            else:
                self.open_tag(tags[0])

    def is_enabled(self, *kwargs):
        return self.gtags is not None

    def tags_to_items(self, tags):
        return [
            [tag.snippet_, '{0}:{1}'.format(tag.filename_, tag.lineno_)]
            for tag in tags
        ]

    def open_tag(self, tag):
        self.view.window().open_file(
            '{0}:{1}'.format(
                os.path.join(self.google3_path, tag.filename_), tag.lineno_
            ),
            ENCODED_POSITION
        )


# clear_on_change to support reloading during plugin development
GoogleTagsCommand.settings.clear_on_change(__file__)
GoogleTagsCommand.settings.add_on_change(__file__,
    GoogleTagsCommand.on_google3_set)
GoogleTagsCommand.on_google3_set()
