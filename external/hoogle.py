import cPickle as pickle

from sys import argv, stdout
from urllib2 import urlopen
from urlparse import urlsplit

from lxml.html import parse


def class_test(name):
    return 'contains(concat(" ", normalize-space(@class), " "), " {0} ")'.format(name)

def query_index(url, tree):
    ANS_XPATH = '//div[{0}]'.format(class_test('ans'))
    DOC_XPATH = './following-sibling::div[{0}][1]//text()'.format(class_test('doc'))
    LOC_XPATH = './following-sibling::div[{0}][1]//text()'.format(class_test('from'))
    URL_XPATH = './/a[1]/@href'

    output = []
    for ans in tree.xpath(ANS_XPATH):
        output.append({
            'name': u''.join(ans.xpath('.//text()')),
            'loc': u''.join(ans.xpath(LOC_XPATH)),
            'doc': u''.join(ans.xpath(DOC_XPATH)),
            'url': unicode(ans.xpath(URL_XPATH)[0])
        })
    return output


def query_details(url, tree):
    return u''.join(tree.xpath('(//*[@name=$name]/../ancestor::div[@class="top"]//div[@class="doc"])[1]//text()', name=urlsplit(url).fragment))


def main():
    if len(argv) != 3:
        raise ValueError('Need exactly 3 arguments')
    handler = {
        'index': query_index,
        'details': query_details
    }.get(argv[1])
    if handler is None:
        raise ValueError('Invalid method')
    tree = parse(urlopen(argv[2]))
    pickle.dump(handler(argv[2], tree), stdout, 2)

if __name__ == '__main__':
    main()
