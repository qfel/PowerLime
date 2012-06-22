from __future__ import division


import sublime

from urllib import urlencode
from urlparse import SplitResult, parse_qs, urlsplit, urlunsplit

from powerlime.help.base import SelectionCommand
from powerlime.util import ExternalPythonCaller


class HoogleCommand(SelectionCommand):
    PROMPT = 'hoogle query'

    hoogle = ExternalPythonCaller('hoogle')

    @staticmethod
    def add_query_args(url, args):
        url = urlsplit(url)._asdict()
        query = parse_qs(url['query'])
        query.update(args)
        url['query'] = urlencode(query)
        return urlunsplit(SplitResult(**url))

    def handle(self, query, internal=True):
        url = self.view.settings().get('hoogle_url',
            'http://www.haskell.org/hoogle/')
        url = self.add_query_args(url, {'hoogle': query})
        results = self.hoogle.query_index(url)
        if results is not None:
            def on_select(index):
                if index == -1:
                    return

                if internal:
                    doc = self.hoogle.query_details(results[index]['url'])
                    if doc is None:
                        return
                    output = win.get_output_panel('hoogle')
                    output.set_read_only(False)
                    edit = output.begin_edit()
                    output.erase(edit, sublime.Region(0, output.size()))
                    output.insert(edit, 0, doc)
                    output.end_edit(edit)
                    output.set_read_only(True)
                    win.run_command('show_panel',
                        {'panel': 'output.hoogle'})
                else:
                    win.run_command('open_url', {
                        'url': results[index]['url']
                    })

            win = self.view.window()
            win.show_quick_panel(
                [[res['name'], res['loc'], res['url']] for res in results],
                on_select
            )
