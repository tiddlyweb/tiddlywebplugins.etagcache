"""
Keep a cache of ETags so we don't need to access the store
to do validation.

This operates as a two tiered piece of middleware.

On the request side it checks if the request is a GET
and if it includes an If-Match header. If it does it
looks up the current URI in the cache and compares the value
with what's in the If-Match header. If they are the same
we can raise a 304 right now.

On the response side, if the current request is a GET
and the outgoing response has an ETag, put the current
URI and ETag into the cache. If the middleware is positioned
correctly these will only be status 200 requests, so the
data is "good".

Concerns: 

* If we cache collection URIs, invalidation is tricky.
  For example a search URI does know that the tiddlers
  within have changed.

Installation is simply adding the plugin name to system_plugins
in tiddlywebconfig.py
"""

import logging
import uuid # for namespacing
import urllib

from tiddlyweb.store import HOOKS
from tiddlyweb.util import sha
from tiddlyweb.web.util import get_serialize_type
from tiddlyweb.web.negotiate import Negotiate
from tiddlyweb.web.http import HTTP304

from tiddlywebplugins.utils import get_store


class EtagCache(object):

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        try:
            _mc = environ['tiddlyweb.store'].storage._mc
        except AttributeError:
            _mc = None
        if _mc:
            self._mc = _mc
            self._check_cache(environ, start_response)

            def replacement_start_response(status, headers, exc_info=None):
                self.status = status
                self.headers = headers
                return start_response(status, headers, exc_info)

            output = self.application(environ, replacement_start_response)

            self._check_response(environ)

            return output
        else:
            return self.application(environ, start_response)

    def _check_cache(self, environ, start_response):
        uri = urllib.quote(environ.get('SCRIPT_NAME', '')
                + environ.get('PATH_INFO', ''))
        prefix = environ.get('tiddlyweb.config', {}).get('server_prefix', '')
        if uri.startswith('%s/bags' % prefix) and 'tiddlers' in uri:
            match = environ.get('HTTP_IF_NONE_MATCH', None)
            if match:
                cached_etag = self._mc.get(self._make_key(environ, uri))
                if cached_etag and cached_etag == match:
                    raise HTTP304(match)

    def _check_response(self, environ):
        if environ['REQUEST_METHOD'] == 'GET':
            uri = urllib.quote(environ.get('SCRIPT_NAME', '')
                    + environ.get('PATH_INFO', ''))
            prefix = environ.get('tiddlyweb.config', {}).get('server_prefix', '')
            if uri.startswith('%s/bags' % prefix) and 'tiddlers' in uri:
                for name, value in self.headers:
                    if name.lower() == 'etag':
                        self._cache(environ, value)

    def _cache(self, environ, value):
        uri = urllib.quote(environ.get('SCRIPT_NAME', '')
                + environ.get('PATH_INFO', ''))
        logging.debug('adding to cache %s:%s' % (uri, value))
        self._mc.set(self._make_key(environ, uri), value)

    def _make_key(self, environ, uri):
        try:
            mime_type = get_serialize_type(environ)[1]
            mime_type = mime_type.split(';', 1)[0].strip()
        except (TypeError, AttributeError):
            mime_type = ''
        username = environ['tiddlyweb.usersign']['name']
        namespace = self._get_namespace(environ, uri)
        key = '%s:%s:%s:%s' % (namespace, mime_type, username, uri)
        return sha(key.encode('UTF-8')).hexdigest()


    def _get_namespace(self, environ, uri):
        prefix = environ.get('tiddlyweb.config', {}).get('server_prefix', '')
        index = 0
        if prefix:
            index = 1
        uri_parts = uri.split('/')[index:]
        bag_name = uri_parts[1]
        tiddler_name = ''
        if len(uri_parts) >= 4:
            tiddler_name = uri_parts[3]
        key = _namespace_key(bag_name, tiddler_name)
        namespace = self._mc.get(key)
        if not namespace:
            namespace = '%s' % uuid.uuid4()
            self._mc.set(key.encode('utf8'), namespace)
        return namespace


def _namespace_key(bag_name, tiddler_name):
    return '%s:%s_namespace' % (bag_name, tiddler_name)


def tiddler_put_hook(store, tiddler):
    bag = tiddler.bag
    title = tiddler.title
    bag_key = _namespace_key(bag, '')
    tiddler_key = _namespace_key(bag, title)
    # This get_store is required to work around confusion with what
    # store is current.
    top_store = get_store(store.environ['tiddlyweb.config'])
    top_store.storage._mc.set(bag_key.encode('utf8'), '%s' % uuid.uuid4())
    top_store.storage._mc.set(tiddler_key.encode('utf8'), '%s' % uuid.uuid4())


def init(config):
    if 'selector' in config:
        if EtagCache not in config['server_request_filters']:
            config['server_request_filters'].insert(
                    config['server_request_filters'].index(Negotiate) + 1,
                    EtagCache)
    if 'cached_store' in config:
        HOOKS['tiddler']['put'].append(tiddler_put_hook)
