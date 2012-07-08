from powerlime.util import CxxSpecificCommand


class SortIncludesCommand(CxxSpecificCommand):
    def run(self, edit):
        def set_sel(region_list):
            sel.clear()
            for region in region_list:
                sel.add(region)

        sel = self.view.sel()
        if len(sel) == 1 and sel[0].empty():
            sel_copy = list(sel)
            set_sel(self.view.find_all(r'^(?:[ \t]*#[ \t]*include[ \t]*(?:"|<)[^\n]+\n)+'))
        else:
            sel_copy = None

        self.view.run_command('sort_lines')

        if sel_copy is not None:
            set_sel(sel_copy)
