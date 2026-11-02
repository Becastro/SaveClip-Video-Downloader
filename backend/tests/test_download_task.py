from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app import tasks
from app.local_store import LocalStore


class FakeYoutubeDL:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def extract_info(self, _url, download):
        assert download is True
        filename = self.options["outtmpl"].replace(
            "%(title).160B - %(id)s.%(ext)s",
            "Authorized_video-test123.mp4",
        )
        Path(filename).write_bytes(b"video-data")
        return {"title": "Authorized video", "id": "test123"}


def test_local_download_stays_successful_after_file_is_created(tmp_path, monkeypatch):
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    monkeypatch.setattr(
        tasks,
        "settings",
        SimpleNamespace(
            download_dir=tmp_path / "downloads",
            standalone=False,
            max_duration_seconds=7200,
            max_file_size_bytes=1000,
            extra_domains=frozenset(),
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(tasks, "local_store", LocalStore(tmp_path / "state.db"))
    tasks.local_store.set_task_state(task_id, {"status": "queued"})
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr(tasks, "validate_url", lambda url, _domains: url)

    selected_dir = tmp_path / "chosen-downloads"
    downloaded = tasks.download_task(
        task_id,
        "https://youtube.com/watch?v=test123",
        "video_720",
        "video",
        download_dir=selected_dir,
    )

    assert Path(downloaded).is_file()
    assert Path(downloaded).parent.parent == selected_dir
    state = tasks.local_store.get_task_state(task_id)
    assert state["status"] == "completed"
    assert state["filename"] == "Authorized_video-test123.mp4"
    assert state["download_dir"] == str(selected_dir)


def test_standalone_download_is_saved_directly_in_selected_folder(
    tmp_path, monkeypatch
):
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    monkeypatch.setattr(
        tasks,
        "settings",
        SimpleNamespace(
            download_dir=tmp_path / "downloads",
            standalone=True,
            max_duration_seconds=7200,
            max_file_size_bytes=1000,
            extra_domains=frozenset(),
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(tasks, "local_store", LocalStore(tmp_path / "state.db"))
    tasks.local_store.set_task_state(task_id, {"status": "queued"})
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setitem(
        sys.modules, "imageio_ffmpeg", SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg")
    )
    monkeypatch.setattr(tasks, "validate_url", lambda url, _domains: url)
    selected_dir = tmp_path / "chosen-downloads"

    downloaded = tasks.download_task(
        task_id,
        "https://youtube.com/watch?v=test123",
        "video_720",
        "video",
        download_dir=selected_dir,
    )

    assert Path(downloaded).parent == selected_dir
    assert Path(downloaded).name == "Authorized_video-test123.mp4"
    assert not (selected_dir / ".saveclip-temp" / task_id).exists()


def test_custom_name_is_used_for_download_without_forcing_an_extension(
    tmp_path, monkeypatch
):
    class CustomNameYoutubeDL(FakeYoutubeDL):
        last_options = None

        def extract_info(self, _url, download):
            assert download is True
            type(self).last_options = self.options
            filename = self.options["outtmpl"].replace("%(ext)s", "mp4")
            Path(filename).write_bytes(b"video-data")
            return {"title": "Original title", "id": "test123"}

    monkeypatch.setattr(
        tasks,
        "settings",
        SimpleNamespace(
            download_dir=tmp_path / "downloads",
            standalone=True,
            max_duration_seconds=7200,
            max_file_size_bytes=1000,
            extra_domains=frozenset(),
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(tasks, "local_store", LocalStore(tmp_path / "state.db"))
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    tasks.local_store.set_task_state(task_id, {"status": "queued"})
    monkeypatch.setitem(
        sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=CustomNameYoutubeDL)
    )
    monkeypatch.setitem(
        sys.modules, "imageio_ffmpeg", SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg")
    )
    monkeypatch.setattr(tasks, "validate_url", lambda url, _domains: url)

    downloaded = tasks.download_task(
        task_id,
        "https://youtube.com/watch?v=test123",
        "video_720",
        "video",
        output_name="Minha aula",
    )

    assert Path(downloaded).name == "Minha aula.mp4"
    assert tasks.local_store.get_task_state(task_id)["filename"] == "Minha aula.mp4"
    assert CustomNameYoutubeDL.last_options["restrictfilenames"] is False


def test_custom_name_is_used_for_multi_item_playlist_folder(tmp_path, monkeypatch):
    class PlaylistYoutubeDL(FakeYoutubeDL):
        def extract_info(self, _url, download):
            assert download is True
            destination = Path(self.options["outtmpl"]).parent
            (destination / "first-item.mp4").write_bytes(b"first")
            (destination / "second-item.mp4").write_bytes(b"second")
            return {
                "title": "Original playlist",
                "entries": [{"title": "First"}, {"title": "Second"}],
            }

    monkeypatch.setattr(
        tasks,
        "settings",
        SimpleNamespace(
            download_dir=tmp_path / "downloads",
            standalone=True,
            max_duration_seconds=7200,
            max_file_size_bytes=1000,
            extra_domains=frozenset(),
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(tasks, "local_store", LocalStore(tmp_path / "state.db"))
    task_id = "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40"
    tasks.local_store.set_task_state(task_id, {"status": "queued"})
    monkeypatch.setitem(
        sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=PlaylistYoutubeDL)
    )
    monkeypatch.setitem(
        sys.modules, "imageio_ffmpeg", SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg")
    )
    monkeypatch.setattr(tasks, "validate_url", lambda url, _domains: url)

    downloaded = tasks.download_task(
        task_id,
        "https://youtube.com/playlist?list=test",
        "video_720",
        "video",
        selected_items=["1", "2"],
        output_name="Aulas selecionadas",
    )

    playlist_folder = Path(downloaded)
    assert playlist_folder.is_dir()
    assert playlist_folder.name == "Aulas selecionadas"
    assert sorted(path.name for path in playlist_folder.iterdir()) == [
        "first-item.mp4",
        "second-item.mp4",
    ]
    assert sorted(path.read_bytes() for path in playlist_folder.iterdir()) == [
        b"first",
        b"second",
    ]
    assert tasks.local_store.get_task_state(task_id)["filename"] == "Aulas selecionadas"
    assert int(tasks.local_store.get_task_state(task_id)["size"]) == 11


def test_wav_audio_download_uses_ffmpeg_wav_conversion(tmp_path, monkeypatch):
    class FakeAudioYoutubeDL(FakeYoutubeDL):
        last_options = None

        def __init__(self, options):
            super().__init__(options)
            type(self).last_options = options

        def extract_info(self, _url, download):
            assert download is True
            filename = self.options["outtmpl"].replace(
                "%(title).160B - %(id)s.%(ext)s",
                "Authorized_audio-test123.wav",
            )
            Path(filename).write_bytes(b"wav-data")
            return {"title": "Authorized audio", "id": "test123"}

    monkeypatch.setattr(
        tasks,
        "settings",
        SimpleNamespace(
            download_dir=tmp_path / "downloads",
            standalone=False,
            max_duration_seconds=7200,
            max_file_size_bytes=1000,
            extra_domains=frozenset(),
            file_ttl_minutes=25,
        ),
    )
    monkeypatch.setattr(tasks, "local_store", LocalStore(tmp_path / "state.db"))
    tasks.local_store.set_task_state(
        "f5324d55-27e1-4ad0-a485-6c8c0b9ab084", {"status": "queued"}
    )
    monkeypatch.setitem(
        sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeAudioYoutubeDL)
    )
    monkeypatch.setattr(tasks, "validate_url", lambda url, _domains: url)

    downloaded = tasks.download_task(
        "f5324d55-27e1-4ad0-a485-6c8c0b9ab084",
        "https://youtube.com/watch?v=test123",
        "audio_wav",
        "audio",
    )

    assert Path(downloaded).suffix == ".wav"
    assert FakeAudioYoutubeDL.last_options["postprocessors"][0] == {
        "key": "FFmpegExtractAudio",
        "preferredcodec": "wav",
        "preferredquality": "192",
    }


@pytest.mark.parametrize(
    ("media_type", "filename", "expected_codec"),
    [
        ("video", "clip.mp4", ("-c:v", "copy", "-c:a", "aac")),
        ("audio", "sound.mp3", ("-c:a", "libmp3lame")),
        ("audio", "sound.m4a", ("-c:a", "aac")),
        ("audio", "sound.wav", ("-c:a", "pcm_s16le")),
    ],
)
def test_output_volume_uses_ffmpeg_and_preserves_video_stream(
    tmp_path, monkeypatch, media_type, filename, expected_codec
):
    output = tmp_path / filename
    output.write_bytes(b"original")
    commands = []

    class FakeProcess:
        def __init__(self, arguments, **_kwargs):
            commands.append(arguments)
            Path(arguments[-1]).write_bytes(b"volume-adjusted")
            self.returncode = 0

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(tasks.subprocess, "Popen", FakeProcess)

    tasks._process_output_volume(output, media_type, 150, "ffmpeg", "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40")

    assert output.read_bytes() == b"volume-adjusted"
    assert not list(tmp_path.glob("*.tmp.*"))
    assert all(value in commands[0] for value in expected_codec)
    assert commands[0][commands[0].index("-af") + 1] == "volume=1.50"


def test_default_output_volume_does_not_reencode_or_change_file(tmp_path, monkeypatch):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"original")
    monkeypatch.setattr(
        tasks.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("100% must preserve the original audio"),
    )

    tasks._process_output_volume(output, "video", 100, "ffmpeg", "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40")

    assert output.read_bytes() == b"original"


def test_output_volume_processing_can_be_cancelled(tmp_path, monkeypatch):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"original")

    class FakeProcess:
        def __init__(self, *_args, **_kwargs):
            self.returncode = None
            self.terminated = False

        def communicate(self, timeout=None):
            if self.terminated:
                self.returncode = -1
                return "", ""
            raise tasks.subprocess.TimeoutExpired("ffmpeg", timeout)

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    monkeypatch.setattr(tasks.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(
        tasks,
        "_get_task_state",
        lambda _task_id: {"status": "cancel_requested"},
    )

    with pytest.raises(tasks.DownloadCancelled):
        tasks._process_output_volume(
            output,
            "video",
            125,
            "ffmpeg",
            "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40",
        )

    assert output.read_bytes() == b"original"


def test_output_volume_respects_configured_file_size_limit(tmp_path, monkeypatch):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"original")

    class FakeProcess:
        def __init__(self, arguments, **_kwargs):
            Path(arguments[-1]).write_bytes(b"output-exceeds-limit")
            self.returncode = 0

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(tasks.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(tasks, "settings", SimpleNamespace(max_file_size_bytes=5))

    with pytest.raises(tasks.OutputVolumeError, match="limite de tamanho"):
        tasks._process_output_volume(
            output,
            "video",
            125,
            "ffmpeg",
            "674c2d75-f5e6-433c-a2e4-bbc01e1b5b40",
        )

    assert output.read_bytes() == b"original"
