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
and the outgoing response has an ETag, put the current
URI and ETag into the cache.

Store HOOKs are used to invalidate the cache through the
management of namespaces.

Installation is simply adding the plugin name to system_plugins
and twanager_plugins in tiddlywebconfig.py
"""

import logging
import uuid  # for namespacing
import urllib

from tiddlyweb.store import HOOKS
from tiddlyweb.util import sha
from tiddlyweb.web.util import get_serialize_type
from tiddlyweb.web.negotiate import Negotiate
from tiddlyweb.web.http import HTTP304, HTTP415

from tiddlywebplugins.utils import get_store


ANY_NAMESPACE = 'any_namespace'
BAGS_NAMESPACE = 'bags_namespace'
RECIPES_NAMESPACE = 'recipes_namespace'


class EtagCache(object):
    """
    Middleware that manages a cache of uri:etag pairs. The
    request half of the app checks the cache and raises 304
    on matches. The response half stores data in the cache.
    """

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
                """
                Record status and headers for later manipulation.
                """
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
        """
        Look in the cache for a match on the current request. That
        request much be a GET and include an If-None-Match header.

        If there is a match, send an immediate 304.
        """
        if environ['REQUEST_METHOD'] == 'GET':
            uri = _get_uri(environ)
            logging.debug('%s with %s %s', __name__, uri,
                    environ['REQUEST_METHOD'])
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
        """
        If the current response is in response to a GET then attempt
        to cache it.
        """
        if environ['REQUEST_METHOD'] == 'GET':
            uri = _get_uri(environ)
            if _cacheable(environ, uri):
                for name, value in self.headers:
                    if name.lower() == 'etag':
                        self._cache(environ, value)

    def _cache(self, environ, value):
        """
        Add the uri and etag to the cache.
        """
        uri = _get_uri(environ)
        logging.debug('%s adding to cache %s:%s', __name__, uri, value)
        self._mc.set(self._make_key(environ, uri), value)

    def _make_key(self, environ, uri):
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
        logging.debug('%s mime_type %s for %s', __name__, mime_type, uri)
        username = environ['tiddlyweb.usersign']['name']
        namespace = self._get_namespace(environ, uri)
        host = environ.get('HTTP_HOST', '')
        key = '%s:%s:%s:%s:%s' % (namespace, mime_type, username, host, uri)
        return sha(key.encode('UTF-8')).hexdigest()

    def _get_namespace(self, environ, uri):
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
            key = _container_namespace_key(container, bag_name, '')
        elif '/recipes/' in uri:
            if '/tiddlers' in uri:
                key = ANY_NAMESPACE
            else:
                container = uri_parts[1]
                recipe_name = uri_parts[2]
                key = _container_namespace_key(container, recipe_name, '')
        # bags or recipes
        elif '/bags' in uri:
            key = BAGS_NAMESPACE
        elif '/recipes' in uri:
            key = RECIPES_NAMESPACE
        # anything that didn't already match, like friendly uris or
        # search
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
    """
    Is the current uri cacheable?
    For the time being attempt to cache anything.
    """
    return True


def _get_uri(environ):
    """
    Reconstruct the current uri from the environment.
    """
    uri = urllib.quote(environ.get('SCRIPT_NAME', '')
            + environ.get('PATH_INFO', ''))
    if environ.get('QUERY_STRING'):
        uri += '?' + environ['QUERY_STRING']
    return uri


def _container_namespace_key(container, entity_name, tiddler_name):
    """
    Construct a namespace key for a container, that may may or may
    not include a tiddler name.
    """
    return '%s:%s:%s_namespace' % (container, entity_name, tiddler_name)


def tiddler_change_hook(store, tiddler):
    """
    When a tiddler changes, the names for the containing bag and
    the any namespace must be reset to invalidate caches.
    """
    bag_name = tiddler.bag
    any_key = ANY_NAMESPACE
    bag_key = _container_namespace_key('bags', bag_name, '')
    logging.debug('%s tiddler change resetting namespace keys, %s, %s',
            __name__, any_key, bag_key)
    # This get_store is required to work around confusion with what
    # store is current.
    top_store = get_store(store.environ['tiddlyweb.config'])
    top_store.storage._mc.set(any_key.encode('utf8'), '%s' % uuid.uuid4())
    top_store.storage._mc.set(bag_key.encode('utf8'), '%s' % uuid.uuid4())


def bag_change_hook(store, bag):
    """
    When a bag changes the namespaces for that bag, all
    bags, and the generic any namespace must be reset to invalidate
    caches.
    """
    bag_name = bag.name
    any_key = ANY_NAMESPACE
    bags_key = BAGS_NAMESPACE
    bag_key = _container_namespace_key('bags', bag_name, '')
    logging.debug('%s bag change resetting namespace keys, %s, %s, %s',
            __name__, any_key, bags_key, bag_key)
    top_store = get_store(store.environ['tiddlyweb.config'])
    top_store.storage._mc.set(any_key.encode('utf8'), '%s' % uuid.uuid4())
    top_store.storage._mc.set(bag_key.encode('utf8'), '%s' % uuid.uuid4())
    top_store.storage._mc.set(bags_key.encode('utf8'), '%s' % uuid.uuid4())


def recipe_change_hook(store, recipe):
    """
    When a recipe changes the namespaces for that recipe, all
    recipes, and the generic any namespace must be reset to invalidate
    caches.
    """
    recipe_name = recipe.name
    any_key = ANY_NAMESPACE
    recipes_key = RECIPES_NAMESPACE
    recipe_key = _container_namespace_key('recipes', recipe_name, '')
    logging.debug('%s: %s recipe change resetting namespace keys, %s, %s, %s',
            store.storage, __name__, any_key, recipes_key, recipe_key)
    top_store = get_store(store.environ['tiddlyweb.config'])
    top_store.storage._mc.set(any_key.encode('utf8'), '%s' % uuid.uuid4())
    top_store.storage._mc.set(recipe_key.encode('utf8'), '%s' % uuid.uuid4())
    top_store.storage._mc.set(recipes_key.encode('utf8'), '%s' % uuid.uuid4())


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
    if 'cached_store' in config:
        HOOKS['tiddler']['put'].append(tiddler_change_hook)
        HOOKS['tiddler']['delete'].append(tiddler_change_hook)
        HOOKS['bag']['put'].append(bag_change_hook)
        HOOKS['bag']['delete'].append(bag_change_hook)
        HOOKS['recipe']['put'].append(recipe_change_hook)
        HOOKS['recipe']['delete'].append(recipe_change_hook)
