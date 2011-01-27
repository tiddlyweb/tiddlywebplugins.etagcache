
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

    tiddler = Tiddler('one', 'place')
    tiddler.text = 'hi'
    store.put(tiddler)

    tiddler = Tiddler('two', 'place')
    tiddler.tags = ['tagged']
    tiddler.text = 'hi'
    store.put(tiddler)

    module.store = store
    #module.http = httplib2.Http('.test_cache')
    module.http = httplib2.Http()
    

def test_simple_get():
    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers/one')

    assert response['status'] == '200'
    assert 'etag' in response

    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers/one',
            headers={'If-None-Match': etag})

    assert response['status'] == '304'

    tiddler = Tiddler('one', 'place')
    tiddler.text = 'bye'
    store.put(tiddler)
    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers/one',
            headers={'If-None-Match': etag})

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers/one')

    assert response['status'] == '200'
    assert 'etag' in response

    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers/one',
            headers={'If-None-Match': etag})

    assert response['status'] == '304'

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers/one',
            headers={'If-None-Match': etag,
                'Accept': 'application/json'})

    assert response['status'] == '200'

    tiddler = Tiddler('one', 'place')
    tiddler.text = 'cow'
    store.put(tiddler)
    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers',
            headers={'If-None-Match': etag})

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers')

    assert response['status'] == '200'
    assert 'etag' in response
