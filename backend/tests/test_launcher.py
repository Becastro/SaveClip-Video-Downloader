import json
import socket
import subprocess

import pytest

from app.security import URLValidationError
from launcher import _download_settings
from launcher import DesktopApi


def test_download_folder_preference_is_loaded_after_restart(tmp_path):
    app_data = tmp_path / "SaveClip"
    app_data.mkdir()
    default_dir = app_data / "downloads"
    chosen_dir = tmp_path / "My Videos"
    older_dir = tmp_path / "Previous Videos"
    settings_file = app_data / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "download_dir": str(chosen_dir),
                "download_dirs": [str(default_dir), str(older_dir), str(chosen_dir)],
            }
        ),
        encoding="utf-8",
    )

    loaded_settings_file, loaded_default_dir, downloads, cleanup_directories = (
        _download_settings(app_data)
    )

    assert loaded_settings_file == settings_file
    assert loaded_default_dir == default_dir
    assert downloads == chosen_dir
    assert cleanup_directories == [default_dir, older_dir, chosen_dir]


def _dns_result(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]


def test_open_in_browser_validates_platform_url_before_launch(monkeypatch):
    opened = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns_result("8.8.8.8"))
    monkeypatch.setattr("webbrowser.open", lambda url, new: opened.append((url, new)) or True)

    result = DesktopApi().open_in_browser("https://youtube.com/watch?v=test")

    assert result is True
    assert opened == [("https://youtube.com/watch?v=test", 2)]


def test_open_in_browser_rejects_non_allowlisted_domains(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, new: opened.append((url, new)) or True)

    with pytest.raises(URLValidationError, match="domínios permitidos"):
        DesktopApi().open_in_browser("https://example.org/")

    assert opened == []


def test_open_download_location_selects_completed_file(
    monkeypatch, tmp_path
):
    from app import main
    from app.local_store import LocalStore

    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    output = tmp_path / "My video.mp4"
    output.write_bytes(b"video")
    store = LocalStore(tmp_path / "state.db")
    store.set_task_state(task_id, {"status": "queued"})
    for status in ("analyzing", "downloading", "processing", "completed"):
        fields = {"status": status}
        if status == "completed":
            fields.update(
                {"download_dir": str(tmp_path), "file_path": str(output)}
            )
        store.set_task_state(task_id, fields)
    monkeypatch.setattr(main, "local_store", store)
    monkeypatch.setattr(main, "settings", type("Settings", (), {"standalone": True})())
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda args: opened.append(args))

    assert DesktopApi().open_download_location(task_id) is True
    assert opened == [["explorer.exe", "/select,", str(output.resolve())]]


def test_open_download_location_rejects_file_outside_download_folder(
    monkeypatch, tmp_path
):
    from app import main
    from app.local_store import LocalStore

    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    store = LocalStore(tmp_path / "state.db")
    store.set_task_state(task_id, {"status": "queued"})
    for status in ("analyzing", "downloading", "processing", "completed"):
        fields = {"status": status}
        if status == "completed":
            fields.update(
                {
                    "download_dir": str(tmp_path / "downloads"),
                    "file_path": str(outside),
                }
            )
        store.set_task_state(task_id, fields)
    monkeypatch.setattr(main, "local_store", store)
    monkeypatch.setattr(main, "settings", type("Settings", (), {"standalone": True})())

    with pytest.raises(ValueError, match="pasta de downloads"):
        DesktopApi().open_download_location(task_id)
