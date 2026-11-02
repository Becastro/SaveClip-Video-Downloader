import hashlib
from io import BytesIO

import pytest

from app import update_ytdlp


class FakeResponse(BytesIO):
    def geturl(self):
        return "https://files.pythonhosted.org/packages/yt_dlp.whl"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_download_verified_wheel_checks_pypi_sha256(monkeypatch):
    wheel_bytes = b"verified test wheel"
    monkeypatch.setattr(
        update_ytdlp,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(wheel_bytes),
    )
    release = {
        "url": "https://files.pythonhosted.org/packages/yt_dlp.whl",
        "sha256": hashlib.sha256(wheel_bytes).hexdigest(),
    }

    path = update_ytdlp.download_verified_wheel(release)
    try:
        assert path.read_bytes() == wheel_bytes
    finally:
        path.unlink()


def test_download_verified_wheel_rejects_hash_mismatch(monkeypatch):
    monkeypatch.setattr(
        update_ytdlp,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"unverified wheel"),
    )

    with pytest.raises(ValueError, match="SHA-256"):
        update_ytdlp.download_verified_wheel(
            {
                "url": "https://files.pythonhosted.org/packages/yt_dlp.whl",
                "sha256": "0" * 64,
            }
        )


def test_declined_update_does_not_install(monkeypatch, capsys):
    monkeypatch.setattr(update_ytdlp, "version", lambda _: "1.0")
    monkeypatch.setattr(
        update_ytdlp,
        "latest_release",
        lambda: {
            "version": "2.0",
            "url": "https://files.pythonhosted.org/packages/yt_dlp.whl",
            "sha256": "a" * 64,
        },
    )
    monkeypatch.setattr("builtins.input", lambda _: "n")
    monkeypatch.setattr(
        update_ytdlp.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("Installer must not run"),
    )

    assert update_ytdlp.main() == 0
    assert "nenhuma alteração foi feita" in capsys.readouterr().out
