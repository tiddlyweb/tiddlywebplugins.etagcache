


def test_compile():
    try:
        import tiddlywebplugins.etagcache
        assert True
    except ImportError, exc:
        assert False, exc
