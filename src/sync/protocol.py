"""Wire formats for operation segments, snapshots, and the sync manifest."""

from __future__ import annotations

import hashlib
import json
from typing import Any

PROTOCOL_VERSION = 1
MANIFEST_PATH = 'manifest.json'
DEVICES_DIR = 'devices'
SNAPSHOTS_DIR = 'snapshots'
OPS_FILENAME = 'ops.jsonl'
SNAPSHOT_FILENAME = 'snapshot.json'


class ProtocolError(ValueError):
    """A remote sync document is malformed or fails verification."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False
    ).encode('utf-8')


def _checksum(document: dict) -> str:
    payload = {key: value for key, value in document.items() if key != 'checksum'}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def seal(document: dict) -> dict:
    result = dict(document)
    result['checksum'] = _checksum(result)
    return result


def verify(document: dict) -> None:
    if not isinstance(document, dict):
        raise ProtocolError('sync document must be an object')
    checksum = document.get('checksum')
    if not isinstance(checksum, str) or checksum != _checksum(document):
        raise ProtocolError('sync document checksum mismatch')


def encode_operation(operation: dict) -> bytes:
    return _canonical(seal(operation)) + b'\n'


def decode_operation(line: bytes | str) -> dict:
    try:
        document = json.loads(line)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f'invalid operation JSON: {exc}') from None
    verify(document)
    required = (
        'id',
        'device_id',
        'lamport',
        'entity',
        'entity_id',
        'op',
        'payload',
        'created_at',
    )
    if any(key not in document for key in required):
        raise ProtocolError('operation is missing required fields')
    if not isinstance(document['lamport'], int) or document['lamport'] < 1:
        raise ProtocolError('operation lamport must be a positive integer')
    if not isinstance(document['payload'], dict):
        raise ProtocolError('operation payload must be an object')
    return document


def encode_operations(operations: list[dict]) -> bytes:
    return b''.join(encode_operation(operation) for operation in operations)


def decode_operations(content: bytes) -> list[dict]:
    operations = []
    for line in content.splitlines():
        if not line.strip():
            continue
        operations.append(decode_operation(line))
    return operations


def encode_snapshot(snapshot: dict) -> bytes:
    return _canonical(seal(snapshot)) + b'\n'


def decode_snapshot(content: bytes) -> dict:
    try:
        document = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f'invalid snapshot JSON: {exc}') from None
    verify(document)
    required = ('device_id', 'lamport', 'tables', 'cursors', 'created_at')
    if any(key not in document for key in required):
        raise ProtocolError('snapshot is missing required fields')
    if not isinstance(document['tables'], dict):
        raise ProtocolError('snapshot tables must be an object')
    if not isinstance(document['cursors'], dict):
        raise ProtocolError('snapshot cursors must be an object')
    return document


def encode_manifest(document: dict) -> bytes:
    return _canonical(seal(document)) + b'\n'


def manifest_document(*, encrypted: bool, salt: str | None = None) -> dict:
    return seal(
        {
            'protocol': PROTOCOL_VERSION,
            'encrypted': encrypted,
            'kdf': 'scrypt' if encrypted else None,
            'salt': salt,
            'created_at': _now(),
        }
    )


def decode_manifest(content: bytes) -> dict:
    try:
        document = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f'invalid manifest JSON: {exc}') from None
    verify(document)
    if document.get('protocol') != PROTOCOL_VERSION:
        raise ProtocolError('unsupported sync protocol version')
    if not isinstance(document.get('encrypted'), bool):
        raise ProtocolError('manifest encryption flag is missing')
    if document['encrypted'] and not isinstance(document.get('salt'), str):
        raise ProtocolError('encrypted manifest is missing a KDF salt')
    return document


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec='seconds')
