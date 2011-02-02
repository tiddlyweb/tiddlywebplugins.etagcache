
import httplib2
from wsgi_intercept import httplib2_intercept
import wsgi_intercept
from tiddlyweb.web.serve import load_app

from tiddlyweb.config import config
from tiddlyweb.store import Store

from tiddlyweb.model.bag import Bag
from tiddlyweb.model.recipe import Recipe
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

    recipe = Recipe('plaice')
    recipe.set_recipe([('place', '')])
    store.put(recipe)

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

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers')

    assert response['status'] == '200'
    etag = response['etag']

    tiddler = Tiddler('one', 'place')
    tiddler.text = 'cow'
    store.put(tiddler)

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers',
            headers={'If-None-Match': etag})

    assert response['status'] == '200'
    assert response['etag'] != etag
    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers',
            headers={'If-None-Match': etag})

    assert response['status'] == '304'
    assert response['etag'] == etag

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers?select=title:two')

    assert response['status'] == '200'
    etag = response['etag']

    tiddler = Tiddler('one', 'place')
    tiddler.text = 'cow'
    store.put(tiddler)

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers?select=title:two',
            headers={'If-None-Match': etag})

    # this is a deep match hit, matching because it was the 'one'
    # tiddler that changed, not 'two'
    assert response['status'] == '304'
    assert response['etag'] == etag

    tiddler = Tiddler('two', 'place')
    tiddler.text = 'thief'
    store.put(tiddler)

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers?select=title:two',
            headers={'If-None-Match': etag})

    assert response['status'] == '200' # total etag miss
    assert response['etag'] != etag

    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/bags/place/tiddlers?select=title:two',
            headers={'If-None-Match': etag})

    assert response['status'] == '304'
    assert response['etag'] == etag

    response, content = http.request(
            'http://our_test_domain:8001/search?q=two')

    assert response['status'] == '200'
    etag = response['etag']

    tiddler = Tiddler('one', 'place')
    tiddler.text = 'cow'
    store.put(tiddler)

    response, content = http.request(
            'http://our_test_domain:8001/search?q=two',
            headers={'If-None-Match': etag})

    # this is a deep match hit, matching because it was the 'one'
    # tiddler that changed, not 'two'
    assert response['status'] == '304'
    assert response['etag'] == etag

    # cause a 200 to refresh cache
    response, content = http.request(
            'http://our_test_domain:8001/search?q=two')
    assert response['status'] == '200'

    response, content = http.request(
            'http://our_test_domain:8001/search?q=two',
            headers={'If-None-Match': etag})
    # this is a cached match hit, matching because it was the 'one'
    # tiddler that changed, not 'two'
    assert response['status'] == '304'
    assert response['etag'] == etag

    # try a recipe
    response, content = http.request(
            'http://our_test_domain:8001/recipes/plaice/tiddlers/two')
    assert response['status'] == '200' # total etag miss
    assert response['etag'] != etag
    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/recipes/plaice/tiddlers/two',
            headers={'If-None-Match': etag})
    assert response['status'] == '304'

    response, content = http.request(
            'http://our_test_domain:8001/recipes/plaice/tiddlers')
    assert response['status'] == '200' # total etag miss
    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/recipes/plaice/tiddlers',
            headers={'If-None-Match': etag})
    assert response['status'] == '304'
    assert response['etag'] == etag

    response, content = http.request(
            'http://our_test_domain:8001/recipes/plaice')
    assert response['status'] == '200' # total etag miss
    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/recipes/plaice',
            headers={'If-None-Match': etag})
    assert response['status'] == '304'
    assert response['etag'] == etag

    recipe = Recipe('plaice')
    recipe.desc = 'oh how now'
    store.put(recipe)

    response, content = http.request(
            'http://our_test_domain:8001/recipes/plaice',
            headers={'If-None-Match': etag})
    assert response['status'] == '200' # miss
    assert response['etag'] == etag


    response, content = http.request(
            'http://our_test_domain:8001/recipes')
    assert response['status'] == '200' # total etag miss
    etag = response['etag']

    response, content = http.request(
            'http://our_test_domain:8001/recipes',
            headers={'If-None-Match': etag})
    assert response['status'] == '304'
    assert response['etag'] == etag

    recipe = Recipe('plaice')
    recipe.desc = 'oh how now'
    store.put(recipe)

    response, content = http.request(
            'http://our_test_domain:8001/recipes')
    assert response['status'] == '200' # total etag miss
    etag = response['etag']
