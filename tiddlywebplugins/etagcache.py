"""
Keep a cache of ETags so we don't need to access the store
to do validation.

This operates as a two tiered piece of middleware.

On the request side it checks if the request is a GET
and if it includes an If-None-Match header. If it does it
looks up the current URI in the cache and compares the value
with what's in the If-Match header. If they are the same
we can raise a 304 right now.

On the response side, if the current request is a GET
and we put the headers in the cache, with the URI as key.
On future requests if the incoming headers have an ETag
we look in the cache.

Store HOOKs are used to invalidate the cache through the
management of namespaces. Those hooks are activated in
tiddlywebplugins.cachingstore, not this module.

Installation is simply adding the plugin name to system_plugins
and twanager_plugins in tiddlywebconfig.py
"""

import logging
import uuid  # for namespacing
import urllib

from httpexceptor import HTTP304, HTTP415

from tiddlyweb.util import sha
from tiddlyweb.web.util import get_serialize_type
from tiddlyweb.web.negotiate import Negotiate
from tiddlywebplugins.caching import (container_namespace_key,
        ANY_NAMESPACE, BAGS_NAMESPACE, RECIPES_NAMESPACE)


LOGGER = logging.getLogger(__name__)
HEADERS_304 = ['etag', 'vary', 'cache-control', 'last-modified',
        'content-location', 'expires']


class Holder(object):
    """
    A simple object for encapsulating response headers through
    a single middleware processing stage and then checking those
    headers against cache.
    """

    def __init__(self, memclient, environ, status=None, headers=None):
        self.memclient = memclient
        self.environ = environ
        self.status = status
        self.headers = headers

    def check_response(self):
        """
        If the current response is in response to a GET then attempt
        to cache it.

        We worry about whether there was an etag on the _next_ request.
        """
        if (self.environ['REQUEST_METHOD'] == 'GET'
                and self.status.startswith('200')):
            uri = _get_uri(self.environ)
            self._cache(uri)

    def _cache(self, uri):
        """
        Add the uri and etag to the cache.
        """
        LOGGER.debug('adding to cache %s:%s', uri, self.headers)
        key = _make_key(self.memclient, self.environ, uri)
        self.memclient.set(key, self.headers)


class EtagCache(object):
    """
    Middleware that manages a cache of uri:etag pairs. The
    request half of the app checks the cache and raises 304
    on matches. The response half stores data in the cache.
    """

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        LOGGER.debug('entering')
        try:
            _memclient = environ['tiddlyweb.store'].storage.mc
        except AttributeError:
            _memclient = None

        if _memclient:
            LOGGER.debug('checking cache')
            _check_cache(_memclient, environ)

            # Create a holder for response details for this current
            # request.
            holder = Holder(_memclient, environ)

            def replacement_start_response(status, headers, exc_info=None):
                """
                Record status and headers for later manipulation.
                """
                holder.status = status
                holder.headers = headers
                return start_response(status, headers, exc_info)

            output = self.application(environ, replacement_start_response)

            LOGGER.debug('checking response')
            holder.check_response()

            return output
        else:
            return self.application(environ, start_response)


def _check_cache(memclient, environ):
    """
    Look in the cache for a match on the current request. That
    request much be a GET and include an If-None-Match header.

    If there is a match, send an immediate 304.
    """
    if environ['REQUEST_METHOD'] == 'GET':
        uri = _get_uri(environ)
        LOGGER.debug('with %s %s', uri, environ['REQUEST_METHOD'])
        match = environ.get('HTTP_IF_NONE_MATCH', None)
        if match:
            LOGGER.debug('has match %s', match)
            key = _make_key(memclient, environ, uri)
            cached_headers = memclient.get(key)
            if cached_headers:
                _testmatch(uri, cached_headers, match)
            else:
                LOGGER.debug('no cached headers for %s', uri)
        else:
            LOGGER.debug('no if none match for %s', uri)


def _testmatch(uri, cached_headers, match):
    """
    If the cached_headers include an Etag, compare that with the incoming
    if-none-match value in match.

    If they are the same, raise a 304 with the relevant stored headers.
    Otherwise we pass through.
    """
    headers_dict = {}
    for name, value in cached_headers:
        name = name.lower()
        # Special case handling of no-transform,
        # which is added by middleware later.
        if name == 'cache-control' and value == 'no-transform':
            continue
        if name in HEADERS_304:
            headers_dict[name] = value

    cached_etag = headers_dict.get('etag')
    LOGGER.debug('comparing cached %s to %s',
            cached_etag, match)
    if cached_etag and cached_etag == match:
        LOGGER.debug('cache hit for %s', uri)
        raise HTTP304(etag=headers_dict['etag'],
                vary=headers_dict.get('vary'),
                cache_control=headers_dict.get('cache-control'),
                last_modified=headers_dict.get('last-modified'),
                content_location=headers_dict.get('content-location'),
                expires=headers_dict.get('expires'))
    else:
        LOGGER.debug('cache miss for %s', uri)


def _get_namespace(memclient, environ, uri):
    """
    Calculate the namespace in which we will look for a match.

    The namespace is built from the current URI.
    """
    prefix = environ.get('tiddlyweb.config', {}).get('server_prefix', '')

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
            key = container_namespace_key(ANY_NAMESPACE)
        else:
            container = uri_parts[1]
            recipe_name = uri_parts[2]
            key = container_namespace_key(container, recipe_name)
    # bags or recipes
    elif '/bags' in uri:
        key = container_namespace_key(BAGS_NAMESPACE)
    elif '/recipes' in uri:
        key = container_namespace_key(RECIPES_NAMESPACE)
    # anything that didn't already match, like friendly uris or
    # search
    else:
        key = container_namespace_key(ANY_NAMESPACE)

    namespace = memclient.get(key)
    if not namespace:
        namespace = '%s' % uuid.uuid4()
        LOGGER.debug('no namespace for %s, setting to %s', key, namespace)
        memclient.set(key.encode('utf8'), namespace)

    LOGGER.debug('current namespace %s:%s', key, namespace)

    return namespace


def _get_uri(environ):
    """
    Reconstruct the current uri from the environment.
    """
    uri = urllib.quote(environ.get('SCRIPT_NAME', '')
            + environ.get('PATH_INFO', ''))
    if environ.get('QUERY_STRING'):
        uri += '?' + environ['QUERY_STRING']
    return uri


def _make_key(memclient, environ, uri):
    """
    Build a key for the current request. The key is a combination
    of the current namespace, the current content type, the current
    user, the host, and the uri.
    """
    try:
        mime_type = get_serialize_type(environ)[1]
        mime_type = mime_type.split(';', 1)[0].strip()
    except (TypeError, AttributeError, HTTP415):
        config = environ['tiddlyweb.config']
        default_serializer = config['default_serializer']
        serializers = config['serializers']
        mime_type = serializers[default_serializer][1]
    LOGGER.debug('mime_type %s for %s', mime_type, uri)
    username = environ['tiddlyweb.usersign']['name']
    namespace = _get_namespace(memclient, environ, uri)
    host = environ.get('HTTP_HOST', '')
    uri = uri.decode('UTF-8', 'replace')
    key = '%s:%s:%s:%s:%s' % (namespace, mime_type, username, host, uri)
    return sha(key.encode('UTF-8')).hexdigest()


def init(config):
    """
    Initialize and configure the plugin. If selector, we are on
    the web server side and need to adjust filters. The rest is
    for both system and twanager plugins: hooks used to invalidate
    the cache.
    """
    if 'selector' in config:
        if EtagCache not in config['server_request_filters']:
            config['server_request_filters'].insert(
                    config['server_request_filters'].index(Negotiate) + 1,
                    EtagCache)
