"""Tests for Nextcloud settings, keyring credentials, and connectivity checks."""

from types import SimpleNamespace

import pytest

import nextcloud
from ledger import Ledger

SYNC_DATA = {
    'base_url': 'cloud.example.test',
    'username': 'test user',
    'password': 'test-password',
    'data_path': 'Savings Funds',
}


@pytest.fixture
def fake_keyring(monkeypatch):
    store = {}

    def get_password(service, username):
        return store.get((service, username))

    def set_password(service, username, password):
        store[(service, username)] = password

    def delete_password(service, username):
        store.pop((service, username), None)

    monkeypatch.setattr(nextcloud.keyring, 'get_password', get_password)
    monkeypatch.setattr(nextcloud.keyring, 'set_password', set_password)
    monkeypatch.setattr(nextcloud.keyring, 'delete_password', delete_password)
    return store


def test_webdav_url_encodes_path_components():
    url = nextcloud.get_file_url(SYNC_DATA, 'sync-v1/devices/a/ops.jsonl')

    assert url == (
        'https://cloud.example.test/remote.php/dav/files/test%20user/'
        'Savings%20Funds/sync-v1/devices/a/ops.jsonl'
    )


def test_base_url_accepts_a_full_https_url_and_rejects_paths():
    assert (
        nextcloud.normalize_base_url('https://cloud.example.test/')
        == 'cloud.example.test'
    )
    assert nextcloud.normalize_base_url('cloud.example.test') == 'cloud.example.test'

    with pytest.raises(ValueError):
        nextcloud.normalize_base_url('https://cloud.example.test/remote.php')
    with pytest.raises(ValueError):
        nextcloud.normalize_base_url('')


def test_ping_accepts_success_and_reports_invalid_credentials(monkeypatch):
    monkeypatch.setattr(
        nextcloud.requests,
        'head',
        lambda *args, **kwargs: SimpleNamespace(status_code=207),
    )
    assert nextcloud.ping_nextcloud_server(SYNC_DATA) == (True, '')

    monkeypatch.setattr(
        nextcloud.requests,
        'head',
        lambda *args, **kwargs: SimpleNamespace(status_code=401),
    )
    assert nextcloud.ping_nextcloud_server(SYNC_DATA) == (False, 'Invalid credentials')


def test_settings_are_stored_in_sqlite_with_the_password_in_the_keyring(
    tmp_path, fake_keyring
):
    ledger = Ledger(tmp_path / 'ledger.db')

    assert nextcloud.save_nextcloud_sync_data_to_db(SYNC_DATA, ledger) is True
    stored = ledger.get_setting('nextcloud_config')
    assert 'test-password' not in stored
    assert 'cloud.example.test' in stored
    assert fake_keyring[(nextcloud.KEYRING_SERVICE, nextcloud.KEYRING_USERNAME)] == (
        'test-password'
    )

    loaded = nextcloud.load_nextcloud_sync_data_from_db(ledger)
    assert loaded == SYNC_DATA


def test_sync_key_is_stored_separately_from_the_nextcloud_password(
    tmp_path, fake_keyring
):
    assert nextcloud.set_sync_key('encoded-key') is True
    assert nextcloud.get_sync_key() == 'encoded-key'
    assert nextcloud.delete_sync_key() is True
    assert nextcloud.get_sync_key() is None


def test_missing_keyring_password_is_reported_without_plaintext(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.db')
    ledger.set_setting(
        'nextcloud_config',
        '{"base_url": "cloud.example.test", "username": "test", '
        '"data_path": "Savings"}',
    )

    with pytest.raises(nextcloud.SyncError, match='password'):
        nextcloud.load_nextcloud_sync_data_from_db(ledger)
