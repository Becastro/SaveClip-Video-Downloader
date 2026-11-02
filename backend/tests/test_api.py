import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.local_store import LocalStore

app = main.app
rate_limit = main.rate_limit


async def allow_requests():
    return None


def setup_function():
    app.dependency_overrides[rate_limit] = allow_requests


def teardown_function():
    app.dependency_overrides.clear()


def test_health_returns_service_status(monkeypatch):
    class FakeRedis:
        def ping(self):
            return True

        def close(self):
            return None

    monkeypatch.setattr("app.main._redis", lambda: FakeRedis())
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}
    assert "yt_dlp" in response.json()


def test_info_rejects_non_allowlisted_domain():
    with TestClient(app) as client:
        response = client.post("/api/info", json={"url": "https://example.org/video.mp4"})
    assert response.status_code == 422
    assert "domínios permitidos" in response.json()["detail"]


def test_info_returns_metadata_formats_and_optional_preview(monkeypatch):
    monkeypatch.setattr("app.main.validate_url", lambda url, _: url)
    monkeypatch.setattr(
        "app.media_formats.validate_public_media_url",
        lambda url: url,
    )
    monkeypatch.setattr(
        "app.main._extract_info",
        lambda *_: {
            "extractor_key": "Youtube",
            "title": "Vídeo de teste",
            "uploader": "Canal",
            "duration": 84,
            "thumbnail": "https://i.ytimg.com/vi/test/hqdefault.jpg",
            "formats": [
                {"height": 360, "vcodec": "avc1", "acodec": "none", "has_drm": False},
                {"height": 720, "vcodec": "avc1", "acodec": "none", "has_drm": False},
                {"height": 1080, "vcodec": "avc1", "acodec": "none", "has_drm": True},
                {"height": None, "vcodec": "none", "acodec": "aac", "has_drm": False},
                {
                    "url": "https://cdn.example/video.mp4",
                    "protocol": "https",
                    "height": 360,
                    "vcodec": "avc1",
                    "acodec": "aac",
                },
                {
                    "url": "https://cdn.example/audio.m4a",
                    "protocol": "https",
                    "vcodec": "none",
                    "acodec": "aac",
                },
            ],
        },
    )
    with TestClient(app) as client:
        response = client.post("/api/info", json={"url": "https://youtube.com/watch?v=test"})
    assert response.status_code == 200
    result = response.json()
    assert result["title"] == "Vídeo de teste"
    assert [item["label"] for item in result["formats"]] == [
        "360p",
        "720p",
        "Melhor qualidade",
        "MP3",
        "M4A",
        "WAV",
    ]
    assert result["preview"] == {
        "video": "https://cdn.example/video.mp4",
        "audio": "https://cdn.example/audio.m4a",
    }


def test_twitter_info_offers_audio_for_unknown_codec_variants(monkeypatch):
    monkeypatch.setattr("app.main.validate_url", lambda url, _: url)
    monkeypatch.setattr(
        "app.main._extract_info",
        lambda *_: {
            "extractor_key": "Twitter",
            "title": "Vídeo do X",
            "formats": [
                {
                    "format_id": "http-2176000",
                    "url": "https://video.twimg.com/ext_tw_video/video.mp4",
                    "vcodec": None,
                    "acodec": None,
                }
            ],
        },
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/info",
            json={"url": "https://x.com/example/status/123"},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["platform"] == "Twitter"
    assert [item["format_id"] for item in result["formats"]] == [
        "video_best",
        "audio_mp3",
        "audio_m4a",
        "audio_wav",
    ]


def test_info_offers_best_video_when_stream_has_no_height(monkeypatch):
    monkeypatch.setattr("app.main.validate_url", lambda url, _: url)
    monkeypatch.setattr(
        "app.main._extract_info",
        lambda *_: {
            "title": "Vídeo sem resolução informada",
            "formats": [],
        },
    )
    with TestClient(app) as client:
        response = client.post("/api/info", json={"url": "https://youtube.com/watch?v=test"})
    assert response.status_code == 200
    assert response.json()["formats"] == []


def test_best_video_format_is_queued(monkeypatch, tmp_path):
    queued = []

    class FakeExecutor:
        def submit(self, function, *args):
            queued.append((function, args))

    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            extra_domains=frozenset(),
            download_dir=tmp_path / "downloads",
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(main, "local_store", LocalStore(tmp_path / "state.db"))
    monkeypatch.setattr(main, "active_downloads", set())
    monkeypatch.setattr(main, "validate_url", lambda url, _: url)
    monkeypatch.setattr(app.state, "download_executor", FakeExecutor(), raising=False)

    response = asyncio.run(
        main.create_download(
            main.DownloadRequest(
                url="https://youtube.com/watch?v=test",
                format_id="video_best",
                type="video",
            )
        )
    )
    assert response["status"] == "queued"
    assert queued[0][1][2] == "video_best"
    assert queued[0][1][-4] == str(tmp_path / "downloads")
    assert queued[0][1][-3] == "{title} - {id}"
    assert queued[0][1][-2] == 100
    assert queued[0][1][-1] is None


def test_download_accepts_selected_output_volume(monkeypatch, tmp_path):
    queued = []

    class FakeExecutor:
        def submit(self, function, *args):
            queued.append((function, args))

    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            extra_domains=frozenset(),
            download_dir=tmp_path / "downloads",
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(main, "local_store", LocalStore(tmp_path / "state.db"))
    monkeypatch.setattr(main, "active_downloads", set())
    monkeypatch.setattr(main, "validate_url", lambda url, _: url)
    monkeypatch.setattr(app.state, "download_executor", FakeExecutor(), raising=False)

    response = asyncio.run(
        main.create_download(
            main.DownloadRequest(
                url="https://youtube.com/watch?v=test",
                format_id="video_best",
                type="video",
                volume_percent=150,
                output_name="Minha aula",
            )
        )
    )

    assert response["status"] == "queued"
    assert queued[0][1][-2] == 150
    assert queued[0][1][-1] == "Minha aula"


def test_download_rejects_invalid_custom_output_name():
    with pytest.raises(HTTPException, match="caracteres inválidos"):
        asyncio.run(
            main.create_download(
                main.DownloadRequest(
                    url="https://youtube.com/watch?v=test",
                    format_id="video_best",
                    type="video",
                    output_name="../video",
                )
            )
        )


def test_download_rejects_volume_outside_supported_range():
    with pytest.raises(ValueError):
        main.DownloadRequest(
            url="https://youtube.com/watch?v=test",
            format_id="thumbnail",
            type="thumbnail",
            volume_percent=201,
        )


def test_thumbnail_download_rejects_non_default_volume(monkeypatch):
    monkeypatch.setattr(main, "validate_url", lambda url, _: url)
    with pytest.raises(HTTPException, match="não se aplica à miniatura"):
        asyncio.run(
            main.create_download(
                main.DownloadRequest(
                    url="https://youtube.com/watch?v=test",
                    format_id="thumbnail",
                    type="thumbnail",
                    volume_percent=150,
                )
            )
        )


def test_wav_audio_format_is_queued(monkeypatch, tmp_path):
    queued = []

    class FakeExecutor:
        def submit(self, function, *args):
            queued.append((function, args))

    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            extra_domains=frozenset(),
            download_dir=tmp_path / "downloads",
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(main, "local_store", LocalStore(tmp_path / "state.db"))
    monkeypatch.setattr(main, "active_downloads", set())
    monkeypatch.setattr(main, "validate_url", lambda url, _: url)
    monkeypatch.setattr(app.state, "download_executor", FakeExecutor(), raising=False)

    response = asyncio.run(
        main.create_download(
            main.DownloadRequest(
                url="https://youtube.com/watch?v=test",
                format_id="audio_wav",
                type="audio",
            )
        )
    )

    assert response["status"] == "queued"
    assert queued[0][1][2:4] == ("audio_wav", "audio")
    assert queued[0][1][-3] == "{title} - {id}"
    assert queued[0][1][-2] == 100
    assert queued[0][1][-1] is None


def test_desktop_executor_uses_configured_concurrency(monkeypatch, tmp_path):
    created = []

    class FakeExecutor:
        def __init__(self, max_workers, thread_name_prefix):
            created.append((max_workers, thread_name_prefix))

        def shutdown(self, wait, cancel_futures):
            return None

    monkeypatch.setattr(main, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            max_concurrent_downloads=3,
            download_dir=tmp_path,
            download_dirs=[tmp_path],
            file_ttl_minutes=25,
        ),
    )

    with TestClient(app):
        assert created == [(3, "saveclip-download")]


def test_output_template_is_validated_and_persisted(monkeypatch, tmp_path):
    settings_file = tmp_path / "SaveClip" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "download_dir": str(tmp_path / "Videos"),
                "download_dirs": [str(tmp_path / "Videos")],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            settings_file=settings_file,
            output_template="{title} - {id}",
        ),
    )

    result = asyncio.run(
        main.set_output_template(
            main.OutputTemplateRequest(output_template="{uploader} - {title}")
        )
    )

    assert result == {"output_template": "{uploader} - {title}"}
    persisted = json.loads(settings_file.read_text(encoding="utf-8"))
    assert persisted["output_template"] == "{uploader} - {title}"
    assert persisted["download_dir"] == str(tmp_path / "Videos")
    assert persisted["download_dirs"] == [str(tmp_path / "Videos")]


def test_output_template_endpoint_rejects_path_separators(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(standalone=True, settings_file=tmp_path / "settings.json"),
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.set_output_template(
                main.OutputTemplateRequest(output_template="../{title}")
            )
        )
    assert error.value.status_code == 422


def test_cancel_download_transitions_queued_task_to_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "local_store", LocalStore(tmp_path / "state.db"))
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    main.local_store.set_task_state(task_id, {"status": "queued"})

    result = asyncio.run(main.cancel_download(task_id))

    assert result["status"] == "cancelled"
    assert main.local_store.get_task_state(task_id)["status"] == "cancelled"


def test_progress_stream_returns_terminal_task_state(monkeypatch, tmp_path):
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    store = LocalStore(tmp_path / "state.db")
    for status in ("queued", "analyzing", "downloading", "processing", "completed"):
        store.set_task_state(task_id, {"status": status, "percent": 100})
    monkeypatch.setattr(main, "local_store", store)

    with TestClient(app) as client:
        response = client.get(f"/api/progress/{task_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"status": "completed"' in response.text


def test_get_file_accepts_direct_saveclip_output_path(monkeypatch, tmp_path):
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    output = tmp_path / "Authorized video.mp4"
    output.write_bytes(b"video")
    store = LocalStore(tmp_path / "state.db")
    store.set_task_state(task_id, {"status": "queued"})
    for status in ("analyzing", "downloading", "processing", "completed"):
        fields = {"status": status}
        if status == "completed":
            fields.update(
                {
                    "download_dir": str(tmp_path),
                    "file_path": str(output),
                    "filename": output.name,
                }
            )
        store.set_task_state(task_id, fields)
    monkeypatch.setattr(main, "local_store", store)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            download_dir=tmp_path,
            download_dirs=[tmp_path],
            max_concurrent_downloads=1,
            file_ttl_minutes=25,
        ),
    )

    with TestClient(app) as client:
        response = client.get(f"/api/file/{task_id}")

    assert response.status_code == 200
    assert response.content == b"video"


def test_playlist_file_endpoints_list_and_serve_folder_contents(monkeypatch, tmp_path):
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    output = tmp_path / "Selected playlist"
    output.mkdir()
    (output / "Lesson 1.mp4").write_bytes(b"first video")
    (output / "Lesson 2.mp4").write_bytes(b"second video")
    store = LocalStore(tmp_path / "state.db")
    for status in ("queued", "analyzing", "downloading", "processing", "completed"):
        fields = {"status": status}
        if status == "completed":
            fields.update(
                {
                    "download_dir": str(tmp_path),
                    "file_path": str(output),
                    "filename": output.name,
                }
            )
        store.set_task_state(task_id, fields)
    monkeypatch.setattr(main, "local_store", store)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            download_dir=tmp_path,
            download_dirs=[tmp_path],
            max_concurrent_downloads=1,
            file_ttl_minutes=25,
        ),
    )

    with TestClient(app) as client:
        manifest = client.get(f"/api/files/{task_id}")
        file_response = client.get(
            f"/api/file/{task_id}/item",
            params={"filename": "Lesson 1.mp4"},
        )
        direct_response = client.get(f"/api/file/{task_id}")

    assert manifest.status_code == 200
    assert manifest.json() == {
        "files": [{"name": "Lesson 1.mp4"}, {"name": "Lesson 2.mp4"}]
    }
    assert file_response.status_code == 200
    assert file_response.content == b"first video"
    assert direct_response.status_code == 409


def test_standalone_cleanup_preserves_completed_downloads(monkeypatch, tmp_path):
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    output = tmp_path / "My video.mp4"
    output.write_bytes(b"saved video")
    old_time = time.time() - 3600
    os.utime(output, (old_time, old_time))
    store = LocalStore(tmp_path / "state.db")
    store.set_task_state(task_id, {"status": "queued"})
    for status in ("analyzing", "downloading", "processing", "completed"):
        store.set_task_state(task_id, {"status": status})
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (old_time, task_id),
        )
    monkeypatch.setattr(main, "local_store", store)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            download_dir=tmp_path,
            download_dirs=[tmp_path],
            file_ttl_minutes=25,
        ),
    )

    main._cleanup_expired_files()

    assert output.read_bytes() == b"saved video"
    assert store.get_task_state(task_id) == {}


def test_download_failure_logs_no_source_url(monkeypatch, tmp_path, caplog):
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    store = LocalStore(tmp_path / "state.db")
    store.set_task_state(task_id, {"status": "queued"})
    monkeypatch.setattr(main, "local_store", store)
    monkeypatch.setattr(main, "active_downloads", {task_id})

    def fail_with_url(*_args):
        raise RuntimeError("Extractor failed at https://example.com/watch?token=secret")

    monkeypatch.setattr("app.tasks.download_task", fail_with_url)
    main._run_local_download(
        task_id,
        "https://example.com/watch?token=secret",
        "video_best",
        "video",
        None,
        str(tmp_path),
        "{title} - {id}",
    )

    assert "secret" not in caplog.text
    assert "https://example.com" not in caplog.text
    assert any(getattr(record, "error_type", None) == "RuntimeError" for record in caplog.records)


def test_desktop_settings_report_first_run_folder_as_unconfigured(monkeypatch, tmp_path):
    settings_file = tmp_path / "SaveClip" / "settings.json"
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            download_dir=tmp_path / "downloads",
            default_download_dir=tmp_path / "downloads",
            settings_file=settings_file,
            standalone=True,
        ),
    )

    assert asyncio.run(main.get_settings())["download_dir_configured"] is False


def test_saving_folder_marks_it_as_configured(monkeypatch, tmp_path):
    settings_file = tmp_path / "SaveClip" / "settings.json"
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            settings_file=settings_file,
            default_download_dir=tmp_path / "downloads",
            download_dir=tmp_path / "downloads",
            download_dirs=[tmp_path / "downloads"],
        ),
    )
    monkeypatch.setattr(main, "active_downloads", set())

    result = asyncio.run(
        main.set_download_folder(
            main.DownloadDirectoryRequest(download_dir=str(tmp_path / "chosen"))
        )
    )

    assert result["download_dir_configured"] is True
    assert settings_file.is_file()


def test_download_folder_can_be_changed_and_restored(monkeypatch, tmp_path):
    default_dir = tmp_path / "SaveClip" / "downloads"
    first_dir = tmp_path / "Videos"
    config_file = tmp_path / "SaveClip" / "settings.json"
    settings = SimpleNamespace(
        standalone=True,
        settings_file=config_file,
        default_download_dir=default_dir,
        download_dir=default_dir,
        download_dirs=[default_dir],
    )
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "active_downloads", set())

    async def change_and_restore():
        changed = await main.set_download_folder(
            main.DownloadDirectoryRequest(download_dir=str(first_dir))
        )
        assert Path(changed["download_dir"]) == first_dir.resolve()
        persisted = json.loads(config_file.read_text(encoding="utf-8"))
        assert persisted["download_dir"] == str(first_dir.resolve())

        restored = await main.set_download_folder(
            main.DownloadDirectoryRequest(download_dir=None)
        )
        assert Path(restored["download_dir"]) == default_dir.resolve()

    asyncio.run(change_and_restore())
    assert first_dir.is_dir()
    assert default_dir.is_dir()


def test_download_folder_cannot_change_while_a_task_is_active(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            standalone=True,
            settings_file=tmp_path / "settings.json",
            default_download_dir=tmp_path / "downloads",
            download_dir=tmp_path / "downloads",
            download_dirs=[tmp_path / "downloads"],
        ),
    )
    monkeypatch.setattr(main, "active_downloads", {"active-task"})

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.set_download_folder(
                main.DownloadDirectoryRequest(download_dir=str(tmp_path / "other"))
            )
        )
    assert error.value.status_code == 409


def test_download_rejects_invalid_format():
    with TestClient(app) as client:
        response = client.post(
            "/api/download",
            json={
                "url": "https://example.org/video.mp4",
                "type": "video",
                "format_id": "raw-format-selector",
            },
        )
    assert response.status_code == 422
    assert "Formato de download inválido" in response.json()["detail"]


def test_progress_rejects_invalid_task_id():
    with TestClient(app) as client:
        response = client.get("/api/progress/not-a-uuid")
    assert response.status_code == 404
