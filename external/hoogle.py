import cPickle as pickle

from sys import argv, stdout
from urllib2 import urlopen
from urlparse import urlsplit

from lxml.html import parse


def class_test(name):
    return 'contains(concat(" ", normalize-space(@class), " "), " {0} ")'.format(name)


def query_index(url):
    ANS_XPATH = '//div[{0}]'.format(class_test('ans'))
    DOC_XPATH = './following-sibling::div[{0}][1]//text()'.format(class_test('doc'))
    LOC_XPATH = './following-sibling::div[{0}][1]//text()'.format(class_test('from'))
    URL_XPATH = './/a[1]/@href'

    tree = parse(urlopen(url))
    output = []
    for ans in tree.xpath(ANS_XPATH):
        output.append({
            'name': u''.join(ans.xpath('.//text()')),
            'loc': u''.join(ans.xpath(LOC_XPATH)),
            'doc': u''.join(ans.xpath(DOC_XPATH)),
            'url': unicode(ans.xpath(URL_XPATH)[0])
        })
    return output


def query_details(url):
    tree = parse(urlopen(url))
    return u''.join(tree.xpath('(//*[@name=$name]/../ancestor::div[@class="top"]//div[@class="doc"])[1]//text()', name=urlsplit(url).fragment))
