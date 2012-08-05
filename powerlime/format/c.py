from sublime import Region, status_message

from powerlime.util import CxxSpecificCommand


class SortIncludesCommand(CxxSpecificCommand):
    SELECTOR = 'meta.preprocessor.c.include'

    def run(self, edit):
        view = self.view
        sels = []
        for sel in view.sel():
            if not sel.empty():
                sels.append(sel)

        if sels:
            for sel in sels:
                for line in view.lines(sel):
                    if view.score_selector(line.a, self.SELECTOR) == 0 or \
                            view.extract_scope(line.a) != line:
                        status_message('Error: selection contains non-includes')
                        return
            for sel in sels:
                self.sort_lines(edit, view.line(sel))
        else:
            self.sort_all_includes(edit)

    def sort_all_includes(self, edit):
        regions = self.view.find_by_selector(self.SELECTOR)
        if not regions:
            return

        regions = iter(regions)
        prev_region = next(regions)
        a = prev_region.a
        b = prev_region.b
        for region in regions:
            if prev_region.b + 1 != region.a or \
                    self.view.substr(prev_region.b) != '\n':  # This feels unnecessary
                self.sort_lines(edit, Region(a, b))
                a = region.a
            b = region.b
            prev_region = region
        self.sort_lines(edit, Region(a, b))

    def sort_lines(self, edit, region):
        view = self.view
        lines = [view.substr(line) for line in view.lines(region)]
        sorted_lines = sorted(lines)
        if sorted_lines != lines:
            view.replace(edit, region, u'\n'.join(sorted_lines))
