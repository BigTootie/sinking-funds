from types import SimpleNamespace

import nextcloud


SYNC_DATA = {
    'base_url': 'cloud.example.test',
    'username': 'test user',
    'password': 'test-password',
    'data_path': 'Savings Funds',
}


def test_webdav_url_encodes_path_components():
    url = nextcloud._get_file_url(SYNC_DATA, 'balance.txt')

    assert url == (
        'https://cloud.example.test/remote.php/dav/files/test%20user/'
        'Savings%20Funds/balance.txt'
    )


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


def test_sync_download_writes_both_files_only_from_responses(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    funds_path = tmp_path / 'funds.json'
    balance_path.write_text('local old balance', encoding='utf-8')
    funds_path.write_text('local old funds', encoding='utf-8')
    monkeypatch.setattr(nextcloud, 'ACCOUNT_BALANCE_FILE', balance_path)
    monkeypatch.setattr(nextcloud, 'FUNDS_FILE', funds_path)

    def get(url, **kwargs):
        payload = b'425.5' if url.endswith('balance.txt') else b'[]'
        return SimpleNamespace(content=payload, raise_for_status=lambda: None)

    monkeypatch.setattr(nextcloud.requests, 'get', get)
    nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert balance_path.read_bytes() == b'425.5'
    assert funds_path.read_bytes() == b'[]'


def test_sync_upload_posts_local_file_to_webdav(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    balance_path.write_text('99.25', encoding='utf-8')
    calls = []

    def put(url, **kwargs):
        calls.append((url, kwargs['auth'], kwargs['data'].read()))
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(nextcloud.requests, 'put', put)
    nextcloud.sync_data_to_nextcloud(balance_path, SYNC_DATA)

    assert calls == [
        ('https://cloud.example.test/remote.php/dav/files/test%20user/Savings%20Funds/balance.txt',
         ('test user', 'test-password'), b'99.25')
    ]
