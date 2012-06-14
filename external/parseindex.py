from lxml.html import parse

def main(path):
    output = []
    tree = parse(open(path))
    for link in tree.xpath('//dt/a[starts-with(@href, "library/")]'):
        output.append((link.get('href'), link.text))
    return output
