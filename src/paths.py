"""Resolve the durable application data directory."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from platformdirs import user_data_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = 'savings-funds'
APP_AUTHOR = 'one.theaustins'


def get_data_dir() -> Path:
    """Return the writable directory that holds the single SQLite database."""
    configured = os.environ.get('FLET_APP_STORAGE_DATA')
    data_dir = (
        Path(configured).expanduser()
        if configured
        else user_data_path(APP_NAME, APP_AUTHOR)
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir.resolve()


def initialize_data_storage(data_dir: Path | None = None) -> None:
    """Create the directory that holds the local database."""
    destination = (data_dir or get_data_dir()).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)


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
