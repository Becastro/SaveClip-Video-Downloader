import socket

import pytest

from app.security import URLValidationError, validate_public_media_url, validate_url


def _dns_result(ip: str):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (ip, 443),
        )
    ]


def test_validate_url_accepts_allowlisted_public_host(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns_result("8.8.8.8"))
    assert validate_url("https://www.youtube.com/watch?v=abc") == "https://www.youtube.com/watch?v=abc"


@pytest.mark.parametrize(
    "url",
    [
        "https://pt.pornhub.com/view_video.php?viewkey=test",
        "https://bunkr.pk/f/test",
        "https://www.bunkr.pk/f/test",
    ],
)
def test_validate_url_rejects_removed_platform_domains(monkeypatch, url):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns_result("8.8.8.8"))
    with pytest.raises(URLValidationError, match="domínios permitidos"):
        validate_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.4", "169.254.1.1"])
def test_validate_url_rejects_non_public_addresses(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns_result(address))
    with pytest.raises(URLValidationError, match="rede privada"):
        validate_url("https://youtube.com/watch?v=abc")


def test_validate_url_rejects_domain_suffix_spoofing():
    with pytest.raises(URLValidationError, match="domínios permitidos"):
        validate_url("https://youtube.com.evil.example/video")


def test_validate_public_media_url_accepts_public_cdn(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns_result("8.8.8.8"))
    url = "https://cdn.example/video.mp4?signature=temporary"
    assert validate_public_media_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/video.mp4",
        "http://localhost/video.mp4",
        "file:///C:/Users/Public/video.mp4",
        "https://cdn.example:8080/video.mp4",
        "https://user:pass@cdn.example/video.mp4",
    ],
)
def test_validate_public_media_url_rejects_local_or_unsafe_addresses(url, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns_result("127.0.0.1"))
    with pytest.raises(URLValidationError):
        validate_public_media_url(url)


def test_validate_public_media_url_rejects_mixed_public_and_private_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _dns_result("8.8.8.8") + _dns_result("10.0.0.4"),
    )
    with pytest.raises(URLValidationError, match="privada"):
        validate_public_media_url("https://cdn.example/video.mp4")
