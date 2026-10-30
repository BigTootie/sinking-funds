"""Pull, merge, and push operation-log documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sync.crypto import CryptoError, SyncCrypto
from sync.protocol import (
    DEVICES_DIR,
    MANIFEST_PATH,
    OPS_FILENAME,
    SNAPSHOT_FILENAME,
    SNAPSHOTS_DIR,
    ProtocolError,
    decode_manifest,
    decode_operations,
    decode_snapshot,
    encode_manifest,
    encode_operations,
    encode_snapshot,
    manifest_document,
)
from sync.provider import SyncProvider, SyncProviderError


class SyncError(Exception):
    """A user-facing synchronization failure."""


@dataclass
class SyncOutcome:
    applied: int = 0
    conflicts: int = 0
    pushed: int = 0
    snapshot_written: bool = False
    last_sync: str | None = None


class SyncEngine:
    """Synchronize a local Ledger with one remote provider."""

    def __init__(
        self,
        ledger,
        provider: SyncProvider,
        *,
        crypto: SyncCrypto | None = None,
        salt: str | None = None,
        passphrase: str | None = None,
    ):
        self.ledger = ledger
        self.provider = provider
        self.crypto = crypto
        self.salt = salt or (crypto.salt if crypto else None)
        self.passphrase = passphrase
        self.device_id = ledger.get_meta('device_id')
        if self.device_id is None:
            raise SyncError('device identity is missing')

    def _decode(self, content: bytes) -> bytes:
        if self.crypto is None:
            return content
        try:
            return self.crypto.decrypt(content)
        except CryptoError as exc:
            raise SyncError(str(exc)) from exc

    def _encode(self, content: bytes) -> bytes:
        return self.crypto.encrypt(content) if self.crypto else content

    def _read_manifest(self) -> dict | None:
        content = self.provider.read_file(MANIFEST_PATH)
        if content is None:
            return None
        try:
            return decode_manifest(content)
        except ProtocolError as exc:
            raise SyncError(str(exc)) from exc

    def _ensure_manifest(self) -> dict:
        manifest = self._read_manifest()
        if manifest is not None:
            if manifest['encrypted']:
                if self.crypto is None:
                    if not self.passphrase:
                        raise SyncError(
                            'This sync folder is encrypted; enter its passphrase.'
                        )
                    self.crypto = SyncCrypto.from_passphrase(
                        self.passphrase, manifest['salt']
                    )
                    self.salt = manifest['salt']
                return manifest
            if self.crypto is not None or self.passphrase:
                raise SyncError('This sync folder is not encrypted.')
            return manifest
        if self.crypto is None and self.passphrase:
            self.crypto = SyncCrypto.from_passphrase(self.passphrase)
            self.salt = self.crypto.salt
        if self.crypto is not None and not self.salt:
            raise SyncError('An encryption salt is required before syncing.')
        manifest = manifest_document(
            encrypted=self.crypto is not None,
            salt=self.salt if self.crypto is not None else None,
        )
        self.provider.write_file(
            MANIFEST_PATH, encode_manifest(manifest), create_only=True
        )
        return manifest

    def _cursors(self) -> dict[str, int]:
        raw = self.ledger.get_sync_state('cursors', '{}') or '{}'
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(values, dict):
            return {}
        return {
            str(device): int(lamport)
            for device, lamport in values.items()
            if isinstance(lamport, int)
        }

    def _save_cursors(self, cursors: dict[str, int]) -> None:
        self.ledger.set_sync_state('cursors', json.dumps(cursors, sort_keys=True))

    def _snapshot_path(self, device_id: str) -> str:
        return f'{SNAPSHOTS_DIR}/{device_id}/{SNAPSHOT_FILENAME}'

    def _ops_path(self, device_id: str) -> str:
        return f'{DEVICES_DIR}/{device_id}/{OPS_FILENAME}'

    def _bootstrap_from_snapshot(self, cursors: dict[str, int]) -> bool:
        if not self.ledger.is_empty():
            return False
        candidates = []
        for device in self.provider.list_devices():
            content = self.provider.read_file(self._snapshot_path(device))
            if content is None:
                continue
            try:
                snapshot = decode_snapshot(self._decode(content))
            except ProtocolError as exc:
                raise SyncError(str(exc)) from exc
            candidates.append(snapshot)
        if not candidates:
            return False
        snapshot = max(candidates, key=lambda item: int(item.get('lamport', 0)))
        if not self.ledger.apply_snapshot(snapshot):
            return False
        snapshot_cursors = snapshot.get('cursors', {})
        for device, lamport in snapshot_cursors.items():
            if isinstance(lamport, int):
                cursors[str(device)] = max(cursors.get(str(device), 0), lamport)
        self._save_cursors(cursors)
        return True

    def _pull(self, cursors: dict[str, int]) -> tuple[int, int]:
        applied = 0
        conflicts = 0
        for device in self.provider.list_devices():
            if device == self.device_id:
                continue
            content = self.provider.read_file(self._ops_path(device))
            if content is None:
                continue
            try:
                operations = decode_operations(self._decode(content))
            except ProtocolError as exc:
                raise SyncError(str(exc)) from exc
            for operation in sorted(operations, key=lambda item: item['lamport']):
                if operation['device_id'] != device:
                    raise SyncError('operation device ID does not match its folder')
                if operation['lamport'] <= cursors.get(device, 0):
                    continue
                try:
                    result = self.ledger.apply_remote_operation(operation)
                except (ProtocolError, ValueError) as exc:
                    raise SyncError(str(exc)) from exc
                if result == 'applied':
                    applied += 1
                elif result == 'conflict':
                    conflicts += 1
                cursors[device] = operation['lamport']
                self._save_cursors(cursors)
        return applied, conflicts

    def _push(self, cursors: dict[str, int]) -> int:
        operations = self.ledger.local_sync_ops()
        if not operations:
            return 0
        payloads = []
        for operation in operations:
            payloads.append(
                {
                    'id': operation['id'],
                    'device_id': operation['device_id'],
                    'lamport': operation['lamport'],
                    'entity': operation['entity'],
                    'entity_id': operation['entity_id'],
                    'op': operation['op'],
                    'payload': json.loads(operation['payload']),
                    'created_at': operation['created_at'],
                }
            )
        self.provider.write_file(
            self._ops_path(self.device_id), self._encode(encode_operations(payloads))
        )
        return len(payloads)

    def _write_snapshot(self, cursors: dict[str, int]) -> bool:
        operations = self.ledger.local_sync_ops()
        if not operations:
            return False
        lamport = max(operation['lamport'] for operation in operations)
        snapshot_cursors = dict(cursors)
        snapshot_cursors[self.device_id] = max(
            snapshot_cursors.get(self.device_id, 0), lamport
        )
        snapshot = {
            'device_id': self.device_id,
            'lamport': lamport,
            'tables': self.ledger.sync_snapshot(),
            'cursors': snapshot_cursors,
            'created_at': datetime.now().isoformat(timespec='seconds'),
        }
        self.provider.write_file(
            self._snapshot_path(self.device_id), self._encode(encode_snapshot(snapshot))
        )
        return True

    def sync(self) -> SyncOutcome:
        try:
            self.provider.ensure_ready()
            self._ensure_manifest()
            self.ledger.ensure_sync_baseline()
            cursors = self._cursors()
            self._bootstrap_from_snapshot(cursors)
            applied, conflicts = self._pull(cursors)
            pushed = self._push(cursors)
            snapshot_written = self._write_snapshot(cursors)
        except SyncError as exc:
            self.ledger.set_sync_state('last_error', str(exc))
            raise
        except (SyncProviderError, OSError) as exc:
            self.ledger.set_sync_state('last_error', str(exc))
            raise SyncError(str(exc)) from exc
        now = datetime.now().isoformat(timespec='seconds')
        self.ledger.set_sync_state('last_sync', now)
        self.ledger.set_sync_state('last_error', '')
        return SyncOutcome(
            applied=applied,
            conflicts=conflicts,
            pushed=pushed,
            snapshot_written=snapshot_written,
            last_sync=now,
        )

    @staticmethod
    def status(ledger) -> dict:
        return {
            'last_sync': ledger.get_sync_state('last_sync'),
            'last_error': ledger.get_sync_state('last_error') or '',
            'conflicts': len(ledger.list_sync_conflicts()),
        }
