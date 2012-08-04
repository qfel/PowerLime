from sublime import Region

from powerlime.util import CxxSpecificCommand


class SortIncludesCommand(CxxSpecificCommand):
    def run(self, edit):
        view = self.view
        regions = view.find_by_selector('meta.preprocessor.c.include')
        if not regions:
            return

        regions = iter(regions)
        prev_region = next(regions)
        a = prev_region.a
        b = prev_region.b
        for region in regions:
            if prev_region.b + 1 != region.a or \
                    view.substr(prev_region.b) != '\n':  # This feels unnecessary
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
