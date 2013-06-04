
import httplib2
from wsgi_intercept import httplib2_intercept
import wsgi_intercept
from tiddlyweb.web.serve import load_app

from tiddlyweb.config import config

from tiddlyweb.model.bag import Bag
from tiddlyweb.model.tiddler import Tiddler

from tiddlywebplugins.utils import get_store

import random
import shutil
import string
import threading


RELEVANT_HEADERS = ['cache-control', 'etag', 'vary', 'last-modified']


def setup_module(module):
    # cleanup
    try:
        shutil.rmtree('store')
    except OSError:
        pass

    # establish web server
    app = load_app()
    def app_fn():
        return app
    httplib2_intercept.install()
    wsgi_intercept.add_wsgi_intercept('our_test_domain', 8001, app_fn)

    module.store = get_store(config)
    module.http = httplib2.Http()


def _random_name(length=5):
    return ''.join(random.choice(string.lowercase) for i in range(length))


def test_single_tiddler():
    bag = Bag(_random_name())
    store.put(bag)

    tiddler = Tiddler(_random_name(), bag.name)
    tiddler.text = _random_name(10)
    store.put(tiddler)

    uri = 'http://our_test_domain:8001/bags/%s/tiddlers/%s' % (
            tiddler.bag, tiddler.title)

    _get_entity(uri)


class RequestThread(threading.Thread):
    """
    Simple thread to test data concurrency.
    """
    def __init__(self, uri, pause=30):
        threading.Thread.__init__(self)
        self.uri = uri
        self.pause = pause
        self.response = None
        self.content = None

    def run(self):
        response, content = http.request(self.uri)
        self.response = response
        self.content = content


def test_thread_safety():
    """
    Non asserting test to exercise threads, demonstrating
    confusion over who has written headers and status information.
    This experiment led to the creation of the Holder object,
    so leaving in for reference.
    """
    bag = Bag(_random_name())
    store.put(bag)

    threads = []
    for i in range(10):
        tiddler = Tiddler(_random_name(), bag.name)
        tiddler.text = _random_name(10)
        store.put(tiddler)
        uri = 'http://our_test_domain:8001/bags/%s/tiddlers/%s' % (
            tiddler.bag, tiddler.title)
        thread = RequestThread(uri)
        threads.append(thread)

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()


def _get_entity(uri):
    response, content = http.request(uri, method='GET')

    assert response['status'] == '200', content
    response_200 = response

    etag = response['etag']

    response, content = http.request(uri, method='GET',
            headers={'If-None-Match': etag})

    assert response['status'] == '304', content
    response_304 = response

    for header in RELEVANT_HEADERS:
        if header in response_200:
            assert header in response_304
            assert response_200[header] == response_304[header]
