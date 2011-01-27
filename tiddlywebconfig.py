# required for testing

import mangler
config = {
        'log_level': 'DEBUG',
        'system_plugins': ['tiddlywebplugins.etagcache'],
        'cached_store' : ['text', {'store_root': 'store'}],
        'server_store': ['tiddlywebplugins.caching', {}],
        }
