"""Nextcloud WebDAV provider for sync documents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import quote, unquote
from xml.etree import ElementTree

import requests

from nextcloud import normalize_base_url
from sync.provider import RemoteConflictError, SyncProviderError

DAV_NAMESPACE = '{DAV:}'
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.25
REQUEST_TIMEOUT = (5, 20)


@dataclass
class WebDAVProvider:
    base_url: str
    username: str
    password: str
    data_path: str
    root_name: str = 'sync-v1'

    def __post_init__(self):
        self.base_url = normalize_base_url(self.base_url)
        self.data_path = self.data_path.strip('/')
        if not self.data_path:
            raise SyncProviderError('Nextcloud data path is required')

    def _url(self, path: str = '') -> str:
        encoded_user = quote(self.username, safe='')
        encoded_path = quote(self.data_path, safe='/')
        encoded_root = quote(self.root_name, safe='')
        url = (
            f'https://{self.base_url}/remote.php/dav/files/{encoded_user}/'
            f'{encoded_path}/{encoded_root}'
        )
        if path:
            url += '/' + quote(path, safe='/')
        return url

    def _request(self, method: str, path: str = '', **kwargs):
        last_error: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = requests.request(
                    method,
                    self._url(path),
                    auth=(self.username, self.password),
                    timeout=REQUEST_TIMEOUT,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code < 500:
                    return response
                last_error = SyncProviderError(
                    f'Nextcloud returned HTTP {response.status_code}'
                )
            if attempt + 1 < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
        raise SyncProviderError(f'Could not reach Nextcloud: {last_error}') from None

    def ensure_ready(self) -> None:
        for path in ('', 'devices', 'snapshots'):
            response = self._request('MKCOL', path)
            if response.status_code not in (201, 405):
                raise SyncProviderError(
                    f'Could not prepare Nextcloud sync folder (HTTP '
                    f'{response.status_code}).'
                )

    def list_devices(self) -> list[str]:
        response = self._request('PROPFIND', 'devices', headers={'Depth': '1'})
        if response.status_code == 404:
            return []
        if response.status_code not in (200, 207):
            raise SyncProviderError(
                f'Could not list Nextcloud sync devices (HTTP {response.status_code}).'
            )
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise SyncProviderError(
                'Nextcloud returned an invalid device list.'
            ) from exc
        devices = set()
        for href in root.findall(f'.//{DAV_NAMESPACE}href'):
            text = (href.text or '').rstrip('/')
            name = unquote(text.rsplit('/', 1)[-1])
            if name and name != 'devices':
                devices.add(name)
        return sorted(devices)

    def read_file(self, path: str) -> bytes | None:
        response = self._request('GET', path)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SyncProviderError(
                f'Could not download sync data (HTTP {response.status_code}).'
            )
        return response.content

    def write_file(
        self,
        path: str,
        content: bytes,
        *,
        if_match: str | None = None,
        create_only: bool = False,
    ) -> str | None:
        headers = {}
        if if_match:
            headers['If-Match'] = if_match
        elif create_only:
            headers['If-None-Match'] = '*'
        response = self._request('PUT', path, data=content, headers=headers)
        if response.status_code == 412:
            raise RemoteConflictError('remote sync data changed during upload')
        if response.status_code not in (200, 201, 204):
            raise SyncProviderError(
                f'Could not upload sync data (HTTP {response.status_code}).'
            )
        return response.headers.get('ETag')

    def delete_file(self, path: str) -> None:
        response = self._request('DELETE', path)
        if response.status_code not in (200, 204, 404):
            raise SyncProviderError(
                f'Could not remove remote sync data (HTTP {response.status_code}).'
            )
