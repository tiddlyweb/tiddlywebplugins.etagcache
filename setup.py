AUTHOR = 'Chris Dent'
AUTHOR_EMAIL = 'cdent@peermore.com'
NAME = 'tiddlywebplugins.etagcache'
DESCRIPTION = 'Cache TiddlyWeb ETags so that a 304 can be sent without checking store'
VERSION = '0.3'


import os

from setuptools import setup, find_packages


# You should carefully review the below (install_requires especially).
setup(
    namespace_packages = ['tiddlywebplugins'],
    name = NAME,
    version = VERSION,
    description = DESCRIPTION,
    long_description = open(os.path.join(os.path.dirname(__file__), 'README')).read(),
    author = AUTHOR,
    author_email = AUTHOR_EMAIL,
    url = 'http://pypi.python.org/pypi/%s' % NAME,
    platforms = 'Posix; MacOS X; Windows',
    packages = find_packages(exclude=['test']),
    install_requires = ['setuptools',
        'tiddlyweb>=1.2.16',
        'tiddlywebplugins.caching>=0.9.4'],
    zip_safe = False
    )
