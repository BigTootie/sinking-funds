"""Operation-log, provider, and two-device synchronization tests."""

import json
from datetime import date
from pathlib import Path

import pytest

from fund import Fund
from ledger import Ledger
from sync.crypto import CryptoError, SyncCrypto
from sync.engine import SyncEngine, SyncError
from sync.protocol import (
    ProtocolError,
    decode_operation,
    decode_operations,
    decode_snapshot,
    encode_operation,
    encode_operations,
    encode_snapshot,
)
from sync.provider import LocalFolderProvider, SyncProviderError


def make_ledger(path):
    return Ledger(Path(path))


def local_engine(ledger, root, **kwargs):
    return SyncEngine(ledger, LocalFolderProvider(root), **kwargs)


def test_operation_protocol_round_trips_and_rejects_tampering():
    operation = {
        'id': 'op-1',
        'device_id': 'device-a',
        'lamport': 1,
        'entity': 'funds',
        'entity_id': 'fund-1',
        'op': 'upsert',
        'payload': {'changes': []},
        'created_at': '2026-10-30T10:00:00',
    }
    encoded = encode_operation(operation)
    assert decode_operation(encoded)['id'] == 'op-1'

    with pytest.raises(ProtocolError):
        decode_operation(encoded.replace(b'op-1', b'op-2'))


def test_operations_file_skips_blank_lines():
    operation = {
        'id': 'op-1',
        'device_id': 'device-a',
        'lamport': 1,
        'entity': 'funds',
        'entity_id': 'fund-1',
        'op': 'upsert',
        'payload': {'changes': []},
        'created_at': '2026-10-30T10:00:00',
    }
    data = encode_operations([operation, operation])
    assert len(decode_operations(data + b'\n')) == 2


def test_crypto_round_trip_and_wrong_key():
    crypto = SyncCrypto.from_passphrase('correct horse battery staple')
    assert crypto.salt
    encrypted = crypto.encrypt(b'secret')
    assert encrypted != b'secret'
    assert crypto.decrypt(encrypted) == b'secret'
    assert SyncCrypto.from_encoded_key(crypto.encoded_key()).decrypt(encrypted) == (
        b'secret'
    )

    other = SyncCrypto.from_passphrase('different passphrase')
    with pytest.raises(CryptoError):
        other.decrypt(encrypted)


def test_local_provider_rejects_path_traversal(tmp_path):
    provider = LocalFolderProvider(tmp_path / 'remote')
    provider.ensure_ready()
    with pytest.raises(SyncProviderError):
        provider.read_file('../escape')


def test_ledger_captures_changes_and_replays_them(tmp_path):
    source = make_ledger(tmp_path / 'source.db')
    target = make_ledger(tmp_path / 'target.db')
    source.add_account('Checking', 'checking', '100')
    operations = source.local_sync_ops()
    assert len(operations) == 1
    payload = decode_operations(
        encode_operations(
            [
                {
                    'id': operations[0]['id'],
                    'device_id': operations[0]['device_id'],
                    'lamport': operations[0]['lamport'],
                    'entity': operations[0]['entity'],
                    'entity_id': operations[0]['entity_id'],
                    'op': operations[0]['op'],
                    'payload': json.loads(operations[0]['payload']),
                    'created_at': operations[0]['created_at'],
                }
            ]
        )
    )[0]

    assert target.apply_remote_operation(payload) == 'applied'
    assert target.list_accounts()[0].name == 'Checking'
    assert target.apply_remote_operation(payload) == 'duplicate'


def test_two_devices_bootstrap_and_exchange_changes(tmp_path):
    a = make_ledger(tmp_path / 'a.db')
    b = make_ledger(tmp_path / 'b.db')
    remote = tmp_path / 'remote'
    a.add_account('Checking', 'checking', '100')

    outcome = local_engine(a, remote).sync()
    assert outcome.pushed >= 1
    assert outcome.snapshot_written is True
    assert (remote / 'manifest.json').is_file()
    assert (remote / 'devices' / a.get_meta('device_id') / 'ops.jsonl').is_file()
    assert (remote / 'snapshots' / a.get_meta('device_id') / 'snapshot.json').is_file()

    assert local_engine(b, remote).sync().applied == 0
    assert [account.name for account in b.list_accounts()] == ['Checking']

    b_fund = Fund('Vacation', 1000, 50)
    b.replace_funds([b_fund])
    local_engine(b, remote).sync()
    local_engine(a, remote).sync()

    assert [fund.name for fund in a.list_funds()] == ['Vacation']


def test_concurrent_edits_are_blocked_until_user_resolves(tmp_path):
    a = make_ledger(tmp_path / 'a.db')
    b = make_ledger(tmp_path / 'b.db')
    remote = tmp_path / 'remote'
    a.add_account('Checking', 'checking', '100')
    local_engine(a, remote).sync()
    local_engine(b, remote).sync()

    account_a = a.list_accounts()[0]
    account_b = b.list_accounts()[0]
    a.update_account(account_a.id, 'A name', 'checking')
    b.update_account(account_b.id, 'B name', 'checking')
    local_engine(a, remote).sync()
    outcome = local_engine(b, remote).sync()

    assert outcome.conflicts == 1
    assert [account.name for account in b.list_accounts()] == ['B name']
    conflict = b.list_sync_conflicts()[0]
    b.resolve_sync_conflict(conflict['id'], 'remote')
    assert [account.name for account in b.list_accounts()] == ['A name']


def test_snapshot_round_trip(tmp_path):
    ledger = make_ledger(tmp_path / 'ledger.db')
    ledger.add_account('Checking', 'checking', '100')
    snapshot = {
        'device_id': ledger.get_meta('device_id'),
        'lamport': 1,
        'tables': ledger.sync_snapshot(),
        'cursors': {},
        'created_at': '2026-10-30T10:00:00',
    }
    encoded = encode_snapshot(snapshot)
    decoded = decode_snapshot(encoded)
    assert decoded['tables']['accounts']


def test_auto_post_on_both_devices_is_idempotent(tmp_path):
    a = make_ledger(tmp_path / 'a.db')
    b = make_ledger(tmp_path / 'b.db')
    remote = tmp_path / 'remote'
    a.add_account('Checking', 'checking', '1000')
    fund = Fund('Car', 5000, recurring_transfer=100, due_day=1)
    a.replace_funds([fund])
    local_engine(a, remote).sync()
    local_engine(b, remote).sync()

    a.auto_post_fund_contributions(funds=a.list_funds(), today=date(2026, 10, 1))
    b.auto_post_fund_contributions(funds=b.list_funds(), today=date(2026, 10, 1))
    local_engine(a, remote).sync()
    local_engine(b, remote).sync()
    local_engine(a, remote).sync()

    assert len(a.list_fund_contributions()) == 1
    assert len(b.list_fund_contributions()) == 1


def test_encrypted_manifest_is_read_without_a_key(tmp_path):
    a = make_ledger(tmp_path / 'a.db')
    remote = tmp_path / 'remote'
    crypto = SyncCrypto.from_passphrase('passphrase')
    a.add_account('Checking', 'checking', '100')
    local_engine(a, remote, crypto=crypto, salt=crypto.salt).sync()

    # A listener without the key can read the manifest but not the data.
    from sync.provider import LocalFolderProvider

    manifest = LocalFolderProvider(remote).read_file('manifest.json')
    assert b'encrypted' in manifest
    with pytest.raises(SyncError):
        local_engine(make_ledger(tmp_path / 'b.db'), remote).sync()


def test_encrypted_sync_accepts_a_passphrase_on_a_second_device(tmp_path):
    a = make_ledger(tmp_path / 'a.db')
    b = make_ledger(tmp_path / 'b.db')
    remote = tmp_path / 'remote'
    crypto = SyncCrypto.from_passphrase('shared passphrase')
    a.add_account('Checking', 'checking', '100')
    local_engine(a, remote, crypto=crypto, salt=crypto.salt).sync()

    listener = local_engine(b, remote, passphrase='shared passphrase')
    outcome = listener.sync()

    assert outcome.applied == 0
    assert [account.name for account in b.list_accounts()] == ['Checking']


def test_existing_database_is_baselined_on_first_sync(tmp_path):
    source = make_ledger(tmp_path / 'source.db')
    target = make_ledger(tmp_path / 'target.db')
    remote = tmp_path / 'remote'
    with source._sync_logging_off():
        source.add_account('Checking', 'checking', '100')
    assert source.local_sync_ops() == []

    local_engine(source, remote).sync()
    local_engine(target, remote).sync()

    assert [account.name for account in target.list_accounts()] == ['Checking']


def test_keeping_the_local_conflict_value_pushes_a_counter_operation(tmp_path):
    a = make_ledger(tmp_path / 'a.db')
    b = make_ledger(tmp_path / 'b.db')
    remote = tmp_path / 'remote'
    a.add_account('Checking', 'checking', '100')
    local_engine(a, remote).sync()
    local_engine(b, remote).sync()

    account_a = a.list_accounts()[0]
    account_b = b.list_accounts()[0]
    a.update_account(account_a.id, 'A name', 'checking')
    b.update_account(account_b.id, 'B name', 'checking')
    local_engine(a, remote).sync()
    local_engine(b, remote).sync()
    conflict = b.list_sync_conflicts()[0]

    b.resolve_sync_conflict(conflict['id'], 'local')
    local_engine(b, remote).sync()
    local_engine(a, remote).sync()

    assert [account.name for account in a.list_accounts()] == ['B name']
