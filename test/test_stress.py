
import httplib2
from wsgi_intercept import httplib2_intercept
import wsgi_intercept
from tiddlyweb.web.serve import load_app

from tiddlyweb.config import config
from tiddlyweb.store import Store

from tiddlyweb.model.bag import Bag
from tiddlyweb.model.tiddler import Tiddler

import os
import shutil
import time

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

    # establish store
    store = Store(config['server_store'][0], config['server_store'][1],
            environ={'tiddlyweb.config': config})

    # make some stuff
    bag = Bag('place')
    store.put(bag)
    for i in range(1, 100):
        tiddler = Tiddler('tiddler%s' % i, 'place')
        tiddler.text = 'hi%s'
        store.put(tiddler)

    module.http = httplib2.Http()


def test_time():
    make_time(8001)


def make_time(port):
    response, content = http.request(
            'http://our_test_domain:%s/bags/place/tiddlers/tiddler5' % port)
    etag = response['etag']
    start = time.time()
    for i in range(1, 2000):
        response, content = http.request(
                'http://our_test_domain:%s/bags/place/tiddlers/tiddler5' % port,
                headers={'If-None-Match': etag})
        assert response['status'] == '304'
        assert response['etag'] == etag
    finish = time.time()
    print start, finish, finish-start
    
    response, content = http.request(
            'http://our_test_domain:%s/bags/place/tiddlers' % port)
    etag = response['etag']
    start = time.time()
    for i in range(1, 500):
        response, content = http.request(
                'http://our_test_domain:%s/bags/place/tiddlers' % port,
                headers={'If-None-Match': etag})
        assert response['status'] == '304'
        assert response['etag'] == etag
    finish = time.time()
    print start, finish, finish-start
