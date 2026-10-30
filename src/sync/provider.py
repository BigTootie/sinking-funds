"""Storage-provider abstraction for sync files."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SyncProviderError(Exception):
    """A remote sync store could not be accessed."""


class RemoteConflictError(SyncProviderError):
    """A remote file changed while a conditional write was in progress."""


class SyncProvider(Protocol):
    def ensure_ready(self) -> None: ...

    def list_devices(self) -> list[str]: ...

    def read_file(self, path: str) -> bytes | None: ...

    def write_file(
        self,
        path: str,
        content: bytes,
        *,
        if_match: str | None = None,
        create_only: bool = False,
    ) -> str | None: ...

    def delete_file(self, path: str) -> None: ...


class LocalFolderProvider:
    """Store sync documents in a local directory, mainly for tests and LAN use."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, path: str) -> Path:
        candidate = (self.root / path).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise SyncProviderError('sync path escapes the storage root')
        return candidate

    def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def list_devices(self) -> list[str]:
        devices = self.root / 'devices'
        if not devices.is_dir():
            return []
        return sorted(
            path.name
            for path in devices.iterdir()
            if path.is_dir() and not path.is_symlink()
        )

    def read_file(self, path: str) -> bytes | None:
        target = self._path(path)
        if not target.is_file():
            return None
        return target.read_bytes()

    def write_file(
        self,
        path: str,
        content: bytes,
        *,
        if_match: str | None = None,
        create_only: bool = False,
    ) -> str | None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if create_only and target.exists():
            raise RemoteConflictError(f'{path} already exists')
        temporary = target.with_name(f'.{target.name}.{os_random()}.tmp')
        temporary.write_bytes(content)
        temporary.replace(target)
        return None

    def delete_file(self, path: str) -> None:
        target = self._path(path)
        if target.is_file():
            target.unlink()


def os_random() -> str:
    from secrets import token_hex

    return token_hex(8)
