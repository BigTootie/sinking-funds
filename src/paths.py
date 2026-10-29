"""Resolve durable application data locations.

Flet runs packaged apps and ``flet run`` with a durable data directory and
exposes it through ``FLET_APP_STORAGE_DATA``. Local development without that
variable falls back to the platform user-data directory.
"""

import os
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

from platformdirs import user_data_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = 'savings-funds'
APP_AUTHOR = 'one.theaustins'

DATA_FILENAMES = (
    'balance.txt',
    'funds.json',
    'budget.json',
    'budget_history.json',
    'nextcloud_sync.json',
    'sync_state.json',
)

MIGRATION_MARKER = '.legacy-data-migrated'


def _set_private_permissions(path: Path) -> None:
    with suppress(OSError):
        path.chmod(0o600)


def get_data_dir() -> Path:
    """Return the writable directory that holds application data.

    Flet provides a per-app storage directory in packaged apps. Direct Python
    launches use the platform user-data directory instead of the working
    directory, which may be read-only or temporary.
    """
    configured = os.environ.get('FLET_APP_STORAGE_DATA')
    data_dir = (
        Path(configured).expanduser()
        if configured
        else user_data_path(APP_NAME, APP_AUTHOR)
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir.resolve()


def open_data_folder() -> None:
    """Open the application data directory in the platform file manager."""
    target = str(get_data_dir())
    if sys.platform == 'win32':
        startfile = getattr(os, 'startfile', None)
        if startfile is None:
            raise OSError('Opening folders is not supported on this platform.')
        startfile(target)
        return

    command = ['open', target] if sys.platform == 'darwin' else ['xdg-open', target]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def initialize_data_storage(
    data_dir: Path | None = None, legacy_dir: Path | None = None
) -> list[Path]:
    """Create the data directory and migrate legacy files once.

    Existing destination files always win.  Migration only runs when the data
    directory differs from the legacy project root, so normal development and
    tests never copy the repository's files into a temporary directory.
    """
    destination = (data_dir or get_data_dir()).expanduser().resolve()
    source = (legacy_dir or PROJECT_ROOT).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / MIGRATION_MARKER
    if destination == source or marker.exists():
        return []

    migrated = []
    for filename in DATA_FILENAMES:
        source_file = source / filename
        destination_file = destination / filename
        if source_file.is_file() and not destination_file.exists():
            shutil.copy2(source_file, destination_file)
            _set_private_permissions(destination_file)
            migrated.append(destination_file)

    # If the marker cannot be written the app can still start; migration will
    # simply be attempted again on the next launch.
    with suppress(OSError):
        marker.touch()
        _set_private_permissions(marker)
    return migrated
