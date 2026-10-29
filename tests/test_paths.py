from pathlib import Path

import paths


def test_data_dir_uses_flet_storage_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('FLET_APP_STORAGE_DATA', str(tmp_path / 'storage'))

    assert paths.get_data_dir() == (tmp_path / 'storage').resolve()
    assert (tmp_path / 'storage').is_dir()


def test_data_dir_falls_back_to_platform_user_data(monkeypatch, tmp_path):
    monkeypatch.delenv('FLET_APP_STORAGE_DATA', raising=False)
    monkeypatch.setattr(
        paths, 'user_data_path', lambda *_args, **_kwargs: tmp_path / 'user-data'
    )
    working = tmp_path / 'working-directory'
    working.mkdir()
    monkeypatch.chdir(working)

    assert paths.get_data_dir() == (tmp_path / 'user-data').resolve()


def test_open_data_folder_uses_platform_file_manager(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(paths, 'get_data_dir', lambda: tmp_path)
    monkeypatch.setattr(paths.sys, 'platform', 'linux')
    monkeypatch.setattr(
        paths.subprocess,
        'Popen',
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    paths.open_data_folder()

    assert calls == [
        (
            ['xdg-open', str(tmp_path)],
            {'stdout': paths.subprocess.DEVNULL, 'stderr': paths.subprocess.DEVNULL},
        )
    ]


def test_legacy_files_are_migrated_without_overwriting(tmp_path):
    legacy = tmp_path / 'legacy'
    destination = tmp_path / 'data'
    legacy.mkdir()
    destination.mkdir()
    (legacy / 'funds.json').write_text('legacy funds', encoding='utf-8')
    (legacy / 'budget_history.json').write_text('legacy history', encoding='utf-8')
    (legacy / 'balance.txt').write_text('legacy balance', encoding='utf-8')
    (destination / 'balance.txt').write_text('current balance', encoding='utf-8')

    migrated = paths.initialize_data_storage(destination, legacy)

    assert {path.name for path in migrated} == {'funds.json', 'budget_history.json'}
    assert (destination / 'funds.json').read_text(encoding='utf-8') == 'legacy funds'
    assert (destination / 'balance.txt').read_text(
        encoding='utf-8'
    ) == 'current balance'


def test_legacy_migration_runs_only_once(tmp_path):
    legacy = tmp_path / 'legacy'
    destination = tmp_path / 'data'
    legacy.mkdir()
    destination.mkdir()
    (legacy / 'funds.json').write_text('first legacy copy', encoding='utf-8')

    assert paths.initialize_data_storage(destination, legacy)
    (destination / 'funds.json').unlink()
    (legacy / 'funds.json').write_text('changed legacy copy', encoding='utf-8')

    assert paths.initialize_data_storage(destination, legacy) == []
    assert not (destination / 'funds.json').exists()


def test_no_migration_when_data_directory_is_project_root(tmp_path):
    (tmp_path / 'funds.json').write_text('[]', encoding='utf-8')

    assert paths.initialize_data_storage(tmp_path, tmp_path) == []
    assert Path(tmp_path / 'funds.json').exists()
