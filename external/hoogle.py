import cPickle as pickle

from sys import argv, exit, stdout
from urllib2 import urlopen

from lxml.html import parse


def class_test(name):
    return 'contains(concat(" ", normalize-space(@class), " "), " {0} ")'.format(name)

ANS_XPATH = '//div[{0}]'.format(class_test('ans'))
DOC_XPATH = './following-sibling::div[{0}][1]//text()'.format(class_test('doc'))
LOC_XPATH = './following-sibling::div[{0}][1]//text()'.format(class_test('from'))
URL_XPATH = './/a[1]/@href'


def main():
    if len(argv) != 2:
        exit(1)

    output = []
    tree = parse(urlopen(argv[1]))
    for ans in tree.xpath(ANS_XPATH):
        output.append({
            'name': u''.join(ans.xpath('.//text()')),
            'loc': u''.join(ans.xpath(LOC_XPATH)),
            'doc': u''.join(ans.xpath(DOC_XPATH)),
            'url': u''.join(ans.xpath(URL_XPATH))
        })

    pickle.dump(output, stdout, 2)

if __name__ == '__main__':
    main()
