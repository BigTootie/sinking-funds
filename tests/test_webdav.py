"""WebDAV provider request-shape and error-handling tests."""

from types import SimpleNamespace

import pytest

from sync.provider import RemoteConflictError, SyncProviderError
from sync.webdav import WebDAVProvider

CONFIG = {
    'base_url': 'cloud.example.test',
    'username': 'test user',
    'password': 'secret',
    'data_path': 'Savings Funds',
}


def make_provider():
    return WebDAVProvider(
        CONFIG['base_url'],
        CONFIG['username'],
        CONFIG['password'],
        CONFIG['data_path'],
    )


def test_webdav_url_encodes_user_and_path():
    provider = make_provider()
    assert provider._url('devices/a/ops.jsonl') == (
        'https://cloud.example.test/remote.php/dav/files/test%20user/'
        'Savings%20Funds/sync-v1/devices/a/ops.jsonl'
    )


def test_ensure_ready_creates_folders(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=201, headers={})

    monkeypatch.setattr('sync.webdav.requests.request', request)
    make_provider().ensure_ready()

    assert [call[0] for call in calls] == ['MKCOL', 'MKCOL', 'MKCOL']
    assert calls[0][1].endswith('/sync-v1')
    assert calls[1][1].endswith('/sync-v1/devices')
    assert calls[2][1].endswith('/sync-v1/snapshots')


def test_read_and_write_use_conditional_headers(monkeypatch):
    def get(method, url, **kwargs):
        return SimpleNamespace(status_code=200, content=b'data', headers={})

    monkeypatch.setattr('sync.webdav.requests.request', get)
    assert make_provider().read_file('manifest.json') == b'data'

    seen = {}

    def put(method, url, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(status_code=201, headers={'ETag': 'abc'})

    monkeypatch.setattr('sync.webdav.requests.request', put)
    etag = make_provider().write_file('manifest.json', b'data', create_only=True)
    assert etag == 'abc'
    assert seen['headers']['If-None-Match'] == '*'


def test_conditional_conflict_is_reported(monkeypatch):
    monkeypatch.setattr(
        'sync.webdav.requests.request',
        lambda *args, **kwargs: SimpleNamespace(status_code=412, headers={}),
    )
    with pytest.raises(RemoteConflictError):
        make_provider().write_file('manifest.json', b'data', if_match='old')


def test_server_errors_raise_provider_error(monkeypatch):
    monkeypatch.setattr(
        'sync.webdav.requests.request',
        lambda *args, **kwargs: SimpleNamespace(status_code=500, content=b''),
    )
    with pytest.raises(SyncProviderError):
        make_provider().read_file('manifest.json')
