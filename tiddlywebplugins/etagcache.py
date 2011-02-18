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

from tiddlyweb.util import sha
from tiddlyweb.web.util import get_serialize_type
from tiddlyweb.web.negotiate import Negotiate
from tiddlyweb.web.http import HTTP304, HTTP415
from tiddlywebplugins.caching import (container_namespace_key,
        ANY_NAMESPACE, BAGS_NAMESPACE, RECIPES_NAMESPACE)


class EtagCache(object):

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        logging.debug('%s entering', __name__)
        try:
            _mc = environ['tiddlyweb.store'].storage._mc
        except AttributeError:
            _mc = None
        if _mc:
            self._mc = _mc
            logging.debug('%s checking cache', __name__)
            self._check_cache(environ, start_response)

            def replacement_start_response(status, headers, exc_info=None):
                self.status = status
                self.headers = headers
                return start_response(status, headers, exc_info)

            output = self.application(environ, replacement_start_response)

            logging.debug('%s checking response', __name__)
            self._check_response(environ)

            return output
        else:
            return self.application(environ, start_response)

    def _check_cache(self, environ, start_response):
        if environ['REQUEST_METHOD'] == 'GET':
            uri = _get_uri(environ)
            logging.debug('%s with %s %s', __name__, uri, environ['REQUEST_METHOD'])
            if _cacheable(environ, uri):
                match = environ.get('HTTP_IF_NONE_MATCH', None)
                if match:
                    logging.debug('%s has match %s', __name__, match)
                    cached_etag = self._mc.get(self._make_key(environ, uri))
                    logging.debug('%s comparing cached %s to %s', __name__,
                            cached_etag, match)
                    if cached_etag and cached_etag == match:
                        logging.debug('%s cache hit for %s', __name__, uri)
                        raise HTTP304(match)
                    else:
                        logging.debug('%s cache miss for %s', __name__, uri)
                else:
                    logging.debug('%s no if none match for %s', __name__, uri)

    def _check_response(self, environ):
        if environ['REQUEST_METHOD'] == 'GET':
            uri = _get_uri(environ)
            if _cacheable(environ, uri):
                for name, value in self.headers:
                    if name.lower() == 'etag':
                        self._cache(environ, value)

    def _cache(self, environ, value):
        uri = _get_uri(environ)
        logging.debug('%s adding to cache %s:%s', __name__, uri, value)
        self._mc.set(self._make_key(environ, uri), value)

    def _make_key(self, environ, uri):
        try:
            mime_type = get_serialize_type(environ)[1]
            mime_type = mime_type.split(';', 1)[0].strip()
        except (TypeError, AttributeError, HTTP415):
            config = environ['tiddlyweb.config']
            default_serializer = config['default_serializer']
            serializers = config['serializers']
            mime_type = serializers[default_serializer][1]
        logging.debug('%s mime_type %s for %s', __name__, mime_type, uri)
        username = environ['tiddlyweb.usersign']['name']
        namespace = self._get_namespace(environ, uri)
        key = '%s:%s:%s:%s' % (namespace, mime_type, username, uri)
        return sha(key.encode('UTF-8')).hexdigest()


    def _get_namespace(self, environ, uri):
        prefix = environ.get('tiddlyweb.config', {}).get('server_prefix', '')
        # one bag or tiddlers in a bag
        index = 0
        if prefix:
            index = 1
        uri_parts = uri.split('/')[index:]
        if '/bags/' in uri:
            container = uri_parts[1]
            bag_name = uri_parts[2]
            key = container_namespace_key(container, bag_name)
        elif '/recipes/' in uri:
            if '/tiddlers' in uri:
                key = ANY_NAMESPACE
            else:
                container = uri_parts[1]
                recipe_name = uri_parts[2]
                key = container_namespace_key(container, recipe_name)
        # bags or recipes
        elif '/bags' in uri:
            key = BAGS_NAMESPACE
        elif '/recipes' in uri:
            key = RECIPES_NAMESPACE
        else:
            key = ANY_NAMESPACE
        namespace = self._mc.get(key)
        if not namespace:
            namespace = '%s' % uuid.uuid4()
            logging.debug('%s no namespace for %s, setting to %s', __name__,
                    key, namespace)
            self._mc.set(key.encode('utf8'), namespace)
        logging.debug('%s current namespace %s:%s', __name__,
                key, namespace)
        return namespace


def _cacheable(environ, uri):
    return True


def _get_uri(environ):
    uri = urllib.quote(environ.get('SCRIPT_NAME', '')
            + environ.get('PATH_INFO', ''))
    if environ.get('QUERY_STRING'):
        uri += '?' + environ['QUERY_STRING']
    return uri


def init(config):
    if 'selector' in config:
        if EtagCache not in config['server_request_filters']:
            config['server_request_filters'].insert(
                    config['server_request_filters'].index(Negotiate) + 1,
                    EtagCache)
