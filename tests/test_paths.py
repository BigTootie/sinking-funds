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


def test_initialization_creates_storage_without_any_data_files(tmp_path):
    destination = tmp_path / 'data'

    assert paths.initialize_data_storage(destination) is None
    assert destination.is_dir()
    assert list(destination.iterdir()) == []
