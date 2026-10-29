import json
import stat
from types import SimpleNamespace

import pytest

import nextcloud
from data import DataCorruptionError, DataFileError

SYNC_DATA = {
    'base_url': 'cloud.example.test',
    'username': 'test user',
    'password': 'test-password',
    'data_path': 'Savings Funds',
}


def funds_payload(fund_id: str, name: str, target: int) -> bytes:
    return json.dumps(
        {
            'version': 2,
            'funds': [
                {
                    'id': fund_id,
                    'name': name,
                    'target': target,
                    'balance': 0,
                    'target_date': 'None',
                    'recurring_transfer': 0,
                }
            ],
        }
    ).encode()


def patch_data_files(monkeypatch, tmp_path):
    paths = {
        'balance': tmp_path / 'balance.txt',
        'funds': tmp_path / 'funds.json',
        'budget': tmp_path / 'budget.json',
        'history': tmp_path / 'budget_history.json',
        'config': tmp_path / 'nextcloud_sync.json',
        'state': tmp_path / 'sync_state.json',
    }
    monkeypatch.setattr(nextcloud, 'ACCOUNT_BALANCE_FILE', paths['balance'])
    monkeypatch.setattr(nextcloud, 'FUNDS_FILE', paths['funds'])
    monkeypatch.setattr(nextcloud, 'BUDGET_FILE', paths['budget'])
    monkeypatch.setattr(nextcloud, 'BUDGET_HISTORY_FILE', paths['history'])
    monkeypatch.setattr(nextcloud, 'NEXTCLOUD_DATA_FILE', paths['config'])
    monkeypatch.setattr(nextcloud, 'SYNC_STATE_FILE', paths['state'])
    return paths


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
    url = nextcloud._get_file_url(SYNC_DATA, 'balance.txt')

    assert url == (
        'https://cloud.example.test/remote.php/dav/files/test%20user/'
        'Savings%20Funds/balance.txt'
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


def test_request_errors_redact_the_password():
    error = nextcloud._request_error(
        nextcloud.requests.ConnectionError('request failed for test-password'),
        SYNC_DATA,
    )

    assert 'test-password' not in str(error)
    assert '[redacted]' in str(error)


def test_reconcile_file_prefers_local_when_only_local_changed():
    assert (
        nextcloud.reconcile_file(b'local', b'remote', nextcloud._file_hash(b'remote'))
        == 'upload'
    )
    assert (
        nextcloud.reconcile_file(b'local', b'remote', nextcloud._file_hash(b'local'))
        == 'download'
    )
    assert nextcloud.reconcile_file(b'local', b'local', None) == 'unchanged'
    assert nextcloud.reconcile_file(b'local', b'remote', None) == 'conflict'
    assert nextcloud.reconcile_file(None, b'remote', None) == 'download'
    assert nextcloud.reconcile_file(None, None, None) == 'create_empty'


def test_sync_download_writes_all_missing_files(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)

    def get(url, **kwargs):
        filename = url.rsplit('/', 1)[-1]
        payload = b'425.5' if filename == 'balance.txt' else b'[]'
        return SimpleNamespace(status_code=200, content=payload)

    monkeypatch.setattr(nextcloud.requests, 'get', get)
    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['balance'].read_bytes() == b'425.5'
    assert paths['funds'].read_bytes() == b'[]'
    assert paths['budget'].read_bytes() == b'[]'
    assert paths['history'].read_bytes() == b'[]'
    assert set(result.downloaded) == {
        paths['balance'],
        paths['funds'],
        paths['budget'],
        paths['history'],
    }


def test_sync_download_creates_missing_remote_files_and_continues(
    monkeypatch, tmp_path
):
    paths = patch_data_files(monkeypatch, tmp_path)
    calls = []

    def get(url, **kwargs):
        filename = url.rsplit('/', 1)[-1]
        calls.append(filename)
        if filename == 'funds.json':
            return SimpleNamespace(status_code=200, content=b'[]')
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(nextcloud.requests, 'get', get)
    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert calls == ['balance.txt', 'funds.json', 'budget.json', 'budget_history.json']
    assert paths['balance'].read_bytes() == b''
    assert paths['funds'].read_bytes() == b'[]'
    assert paths['budget'].read_bytes() == b''
    assert paths['history'].read_bytes() == b''
    assert set(result.created) == {paths['balance'], paths['budget'], paths['history']}
    assert set(result.uploads) == {paths['balance'], paths['budget'], paths['history']}


def test_sync_download_keeps_existing_local_file_when_remote_file_is_missing(
    monkeypatch, tmp_path
):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('123.45', encoding='utf-8')
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(status_code=404),
    )

    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['balance'].read_text(encoding='utf-8') == '123.45'
    assert paths['funds'].read_bytes() == b''
    assert paths['budget'].read_bytes() == b''
    assert paths['history'].read_bytes() == b''
    assert set(result.uploads) == {
        paths['balance'],
        paths['funds'],
        paths['budget'],
        paths['history'],
    }


@pytest.mark.parametrize('local_payload', [b'', b'-1'])
def test_blank_or_unset_local_balance_downloads_remote_data(
    monkeypatch, tmp_path, local_payload
):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_bytes(local_payload)
    remote = b'425.50'

    def get(url, **kwargs):
        if url.endswith('balance.txt'):
            return SimpleNamespace(
                status_code=200, content=remote, headers={'ETag': '"remote"'}
            )
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(nextcloud.requests, 'get', get)
    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['balance'].read_bytes() == remote
    assert paths['balance'] in result.downloaded
    assert paths['balance'] not in result.uploads
    assert paths['balance'] not in result.conflicts


@pytest.mark.parametrize('remote_payload', [b'', b'-1'])
def test_blank_or_unset_remote_balance_does_not_erase_local_data(
    monkeypatch, tmp_path, remote_payload
):
    paths = patch_data_files(monkeypatch, tmp_path)
    local = b'123.45'
    paths['balance'].write_bytes(local)

    def get(url, **kwargs):
        if url.endswith('balance.txt'):
            return SimpleNamespace(
                status_code=200, content=remote_payload, headers={'ETag': '"remote"'}
            )
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(nextcloud.requests, 'get', get)
    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['balance'].read_bytes() == local
    assert paths['balance'] in result.uploads
    assert paths['balance'] not in result.downloaded
    assert paths['balance'] not in result.conflicts
    state = json.loads(paths['state'].read_text(encoding='utf-8'))
    assert 'etag' not in state['files']['balance.txt']


def test_sync_conflict_keeps_both_copies_and_queues_upload(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    local = funds_payload('local-id', 'Local', 100)
    remote = funds_payload('remote-id', 'Remote', 200)
    paths['funds'].write_bytes(local)
    paths['state'].write_text(
        json.dumps({'files': {'funds.json': {'hash': 'previous', 'etag': '"old"'}}}),
        encoding='utf-8',
    )

    def get(url, **kwargs):
        if url.endswith('funds.json'):
            return SimpleNamespace(
                status_code=200, content=remote, headers={'ETag': '"new"'}
            )
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(nextcloud.requests, 'get', get)
    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['funds'].read_bytes() == local
    assert result.conflicts
    assert result.conflicts[0].read_bytes() == remote
    assert paths['funds'] in result.uploads
    state = json.loads(paths['state'].read_text(encoding='utf-8'))
    assert 'etag' not in state['files']['funds.json']


def test_remote_missing_clears_stale_etag_before_upload(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('123.45', encoding='utf-8')
    paths['state'].write_text(
        json.dumps({'files': {'balance.txt': {'hash': 'previous', 'etag': '"old"'}}}),
        encoding='utf-8',
    )
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(status_code=404),
    )

    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['balance'] in result.uploads
    state = json.loads(paths['state'].read_text(encoding='utf-8'))
    assert 'etag' not in state['files']['balance.txt']


def test_invalid_remote_data_is_rejected_without_overwriting_local(
    monkeypatch, tmp_path
):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['funds'].write_text('local version', encoding='utf-8')

    def get(url, **kwargs):
        if url.endswith('funds.json'):
            return SimpleNamespace(status_code=200, content=b'not json')
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(nextcloud.requests, 'get', get)

    with pytest.raises(nextcloud.SyncError):
        nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['funds'].read_text(encoding='utf-8') == 'local version'
    assert not list(tmp_path.glob('*.corrupt-*'))


def test_semantically_invalid_remote_data_is_rejected_before_writing(
    monkeypatch, tmp_path
):
    paths = patch_data_files(monkeypatch, tmp_path)
    local = funds_payload('local-id', 'Local', 100)
    paths['funds'].write_bytes(local)

    def get(url, **kwargs):
        if url.endswith('funds.json'):
            return SimpleNamespace(
                status_code=200, content=b'{"version": 2, "funds": "not a list"}'
            )
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(nextcloud.requests, 'get', get)

    with pytest.raises(nextcloud.SyncError):
        nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['funds'].read_bytes() == local
    assert not paths['balance'].exists()


def test_failed_fetch_does_not_apply_earlier_downloads(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)

    def get(url, **kwargs):
        if url.endswith('balance.txt'):
            return SimpleNamespace(status_code=200, content=b'425.50')
        raise nextcloud.requests.ConnectionError('offline')

    monkeypatch.setattr(nextcloud.requests, 'get', get)

    with pytest.raises(nextcloud.SyncError):
        nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert not paths['balance'].exists()
    assert not paths['funds'].exists()


def test_invalid_local_file_is_preserved_and_replaced_by_valid_remote(
    monkeypatch, tmp_path
):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['funds'].write_text('broken local data', encoding='utf-8')
    remote = funds_payload('remote-id', 'Remote', 200)

    def get(url, **kwargs):
        if url.endswith('funds.json'):
            return SimpleNamespace(status_code=200, content=remote)
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(nextcloud.requests, 'get', get)
    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['funds'].read_bytes() == remote
    assert len(result.invalid_locals) == 1
    assert result.invalid_locals[0].read_text(encoding='utf-8') == 'broken local data'
    assert paths['funds'] not in result.uploads


def test_invalid_local_file_is_preserved_when_remote_is_missing(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('not money', encoding='utf-8')
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(status_code=404),
    )

    result = nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['balance'].read_bytes() == b''
    assert len(result.invalid_locals) == 1
    assert result.invalid_locals[0].read_text(encoding='utf-8') == 'not money'
    assert paths['balance'] in result.uploads


def test_newer_local_schema_is_preserved_during_sync(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['funds'].write_text(
        json.dumps({'version': 99, 'funds': []}), encoding='utf-8'
    )
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(status_code=404),
    )

    with pytest.raises(DataFileError):
        nextcloud.sync_data_from_nextcloud(SYNC_DATA)

    assert paths['funds'].exists()
    assert not list(tmp_path.glob('funds.json.corrupt-*'))


def test_sync_upload_puts_local_file_and_records_etag(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('99.25', encoding='utf-8')
    calls = []

    def put(url, **kwargs):
        calls.append((url, kwargs['auth'], kwargs['data'], kwargs['headers']))
        return SimpleNamespace(status_code=201, headers={'ETag': '"abc"'})

    monkeypatch.setattr(nextcloud.requests, 'put', put)
    nextcloud.sync_data_to_nextcloud(paths['balance'], SYNC_DATA)

    assert calls == [
        (
            'https://cloud.example.test/remote.php/dav/files/test%20user/'
            'Savings%20Funds/balance.txt',
            ('test user', 'test-password'),
            b'99.25',
            {},
        )
    ]
    state = json.loads(paths['state'].read_text(encoding='utf-8'))
    assert state['files']['balance.txt']['etag'] == '"abc"'

    calls.clear()
    nextcloud.sync_data_to_nextcloud(paths['balance'], SYNC_DATA)
    assert calls[0][3] == {'If-Match': '"abc"'}


def test_sync_upload_reports_remote_conflict(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('99.25', encoding='utf-8')
    monkeypatch.setattr(
        nextcloud.requests,
        'put',
        lambda *args, **kwargs: SimpleNamespace(status_code=412, headers={}),
    )
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, content=b'97.00', headers={'ETag': '"remote"'}
        ),
    )

    with pytest.raises(nextcloud.SyncConflictError):
        nextcloud.sync_data_to_nextcloud(paths['balance'], SYNC_DATA)


def test_sync_upload_retries_when_only_the_etag_changed(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('99.25', encoding='utf-8')
    paths['state'].write_text(
        json.dumps(
            {
                'files': {
                    'balance.txt': {
                        'hash': nextcloud._file_hash(b'98.00'),
                        'etag': '"stale"',
                    }
                }
            }
        ),
        encoding='utf-8',
    )
    puts = []

    def put(_url, **kwargs):
        puts.append(kwargs['headers'])
        if len(puts) == 1:
            return SimpleNamespace(status_code=412, headers={})
        return SimpleNamespace(status_code=201, headers={'ETag': '"new"'})

    monkeypatch.setattr(nextcloud.requests, 'put', put)
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, content=b'98.00', headers={'ETag': '"remote"'}
        ),
    )

    nextcloud.sync_data_to_nextcloud(paths['balance'], SYNC_DATA)

    assert puts == [{'If-Match': '"stale"'}, {}]
    state = json.loads(paths['state'].read_text(encoding='utf-8'))
    assert state['files']['balance.txt']['etag'] == '"new"'


def test_sync_upload_accepts_remote_content_equal_to_local(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('99.25', encoding='utf-8')
    puts = []

    def put(_url, **kwargs):
        puts.append(kwargs['headers'])
        return SimpleNamespace(status_code=412, headers={})

    monkeypatch.setattr(nextcloud.requests, 'put', put)
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, content=b'99.25', headers={'ETag': '"same"'}
        ),
    )

    nextcloud.sync_data_to_nextcloud(paths['balance'], SYNC_DATA)

    assert puts == [{}]
    state = json.loads(paths['state'].read_text(encoding='utf-8'))
    assert state['files']['balance.txt']['etag'] == '"same"'


def test_sync_upload_retries_when_remote_file_was_deleted(monkeypatch, tmp_path):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['balance'].write_text('99.25', encoding='utf-8')
    paths['state'].write_text(
        json.dumps({'files': {'balance.txt': {'hash': 'old', 'etag': '"stale"'}}}),
        encoding='utf-8',
    )
    puts = []

    def put(_url, **kwargs):
        puts.append(kwargs['headers'])
        if len(puts) == 1:
            return SimpleNamespace(status_code=412, headers={})
        return SimpleNamespace(status_code=201, headers={'ETag': '"new"'})

    monkeypatch.setattr(nextcloud.requests, 'put', put)
    monkeypatch.setattr(
        nextcloud.requests,
        'get',
        lambda *args, **kwargs: SimpleNamespace(status_code=404),
    )

    nextcloud.sync_data_to_nextcloud(paths['balance'], SYNC_DATA)

    assert puts == [{'If-Match': '"stale"'}, {}]


def test_nextcloud_settings_are_private_and_corruption_is_preserved(
    monkeypatch, tmp_path
):
    paths = patch_data_files(monkeypatch, tmp_path)
    assert nextcloud.load_nextcloud_sync_data() is None

    nextcloud.save_nextcloud_sync_data(SYNC_DATA)
    assert nextcloud.load_nextcloud_sync_data() == SYNC_DATA
    assert stat.S_IMODE(paths['config'].stat().st_mode) == 0o600
    assert nextcloud.credential_storage_warning() is not None
    assert (
        json.loads(paths['config'].read_text(encoding='utf-8'))['password']
        == 'test-password'
    )
    assert not list((tmp_path / 'backups').glob('nextcloud_sync-*.bak'))

    nextcloud.save_nextcloud_sync_data(None)
    assert nextcloud.load_nextcloud_sync_data() is None

    paths['config'].write_text('{broken', encoding='utf-8')
    with pytest.raises(DataCorruptionError) as error:
        nextcloud.load_nextcloud_sync_data()
    assert error.value.quarantine_path is not None
    assert error.value.quarantine_path.exists()


def test_nextcloud_password_is_stored_in_the_os_keyring(
    monkeypatch, tmp_path, fake_keyring
):
    paths = patch_data_files(monkeypatch, tmp_path)
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    old_backup = backup_dir / 'nextcloud_sync-20260101-000000-000000.json.bak'
    old_backup.write_text('{"password": "old-secret"}', encoding='utf-8')

    nextcloud.save_nextcloud_sync_data(SYNC_DATA)

    saved = json.loads(paths['config'].read_text(encoding='utf-8'))
    assert 'password' not in saved
    assert not old_backup.exists()
    assert (
        fake_keyring[(nextcloud.KEYRING_SERVICE, nextcloud.KEYRING_USERNAME)]
        == 'test-password'
    )
    assert nextcloud.load_nextcloud_sync_data() == SYNC_DATA
    assert nextcloud.credential_storage_warning() is None


def test_legacy_plaintext_password_migrates_to_the_keyring(
    monkeypatch, tmp_path, fake_keyring
):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['config'].write_text(json.dumps(SYNC_DATA), encoding='utf-8')

    assert nextcloud.load_nextcloud_sync_data() == SYNC_DATA

    saved = json.loads(paths['config'].read_text(encoding='utf-8'))
    assert 'password' not in saved
    assert (
        fake_keyring[(nextcloud.KEYRING_SERVICE, nextcloud.KEYRING_USERNAME)]
        == 'test-password'
    )


def test_missing_keyring_password_reports_an_actionable_error(
    monkeypatch, tmp_path, fake_keyring
):
    paths = patch_data_files(monkeypatch, tmp_path)
    paths['config'].write_text(
        json.dumps(
            {
                'base_url': SYNC_DATA['base_url'],
                'username': SYNC_DATA['username'],
                'data_path': SYNC_DATA['data_path'],
            }
        ),
        encoding='utf-8',
    )

    with pytest.raises(DataFileError, match='OS keyring'):
        nextcloud.load_nextcloud_sync_data()

    assert paths['config'].exists()
    assert not list(tmp_path.glob('nextcloud_sync.json.corrupt-*'))


def test_disabling_nextcloud_removes_the_keyring_password(
    monkeypatch, tmp_path, fake_keyring
):
    paths = patch_data_files(monkeypatch, tmp_path)
    nextcloud.save_nextcloud_sync_data(SYNC_DATA)

    nextcloud.save_nextcloud_sync_data(None)

    assert not fake_keyring
    assert json.loads(paths['config'].read_text(encoding='utf-8')) == {}
    assert nextcloud.load_nextcloud_sync_data() is None
