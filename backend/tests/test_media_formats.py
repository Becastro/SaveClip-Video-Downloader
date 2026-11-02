from app.media_formats import build_available_formats, build_preview_sources, platform_name


def test_format_choices_only_include_formats_present_in_metadata():
    formats = build_available_formats(
        {
            "formats": [
                {"height": 480, "vcodec": "avc1", "acodec": "none"},
                {"height": 720, "vcodec": "avc1", "acodec": "none"},
                {"height": 1080, "vcodec": "avc1", "acodec": "none", "has_drm": True},
                {"height": None, "vcodec": "none", "acodec": "aac"},
            ]
        }
    )

    assert [item["format_id"] for item in formats] == [
        "video_480",
        "video_720",
        "video_best",
        "audio_mp3",
        "audio_m4a",
        "audio_wav",
    ]


def test_format_choices_do_not_invent_video_or_audio_streams():
    assert build_available_formats({"formats": []}) == []
    assert build_available_formats(
        {"formats": [{"height": 1080, "vcodec": "avc1", "acodec": "none", "has_drm": True}]}
    ) == []


def test_twitter_video_offers_audio_when_extractor_does_not_report_codec():
    formats = build_available_formats(
        {
            "extractor_key": "Twitter",
            "formats": [
                {
                    "format_id": "http-2176000",
                    "url": "https://video.twimg.com/ext_tw_video/video.mp4",
                    "height": None,
                    "vcodec": None,
                    "acodec": None,
                }
            ],
        }
    )

    assert [item["format_id"] for item in formats] == [
        "video_best",
        "audio_mp3",
        "audio_m4a",
        "audio_wav",
    ]


def test_unknown_audio_codec_on_other_platform_does_not_enable_audio():
    formats = build_available_formats(
        {
            "extractor_key": "OtherPlatform",
            "formats": [{"format_id": "1", "vcodec": None, "acodec": None}],
        }
    )

    assert formats == []


def test_playlist_uses_first_available_entry_for_format_choices():
    formats = build_available_formats(
        {
            "entries": [
                None,
                {"formats": [{"height": 360, "vcodec": "avc1", "acodec": "none"}]},
            ]
        }
    )
    assert [item["format_id"] for item in formats] == ["video_360", "video_best"]


def test_platform_name_falls_back_to_extractor_or_generic_label():
    assert platform_name("https://example.com/video", "Generic") == "Generic"
    assert platform_name("https://example.com/video", None) == "Plataforma suportada"


def test_preview_sources_choose_browser_playable_video_and_audio(monkeypatch):
    from app import media_formats

    monkeypatch.setattr(
        media_formats,
        "validate_public_media_url",
        lambda url: url,
    )
    result = build_preview_sources(
        {
            "formats": [
                {
                    "url": "https://media.example/video-360.mp4",
                    "protocol": "https",
                    "vcodec": "avc1",
                    "acodec": "aac",
                    "height": 360,
                },
                {
                    "url": "https://media.example/video-720.mp4",
                    "protocol": "https",
                    "vcodec": "avc1",
                    "acodec": "aac",
                    "height": 720,
                },
                {
                    "url": "https://media.example/audio.m4a",
                    "protocol": "https",
                    "vcodec": "none",
                    "acodec": "aac",
                    "abr": 128,
                },
            ]
        }
    )

    assert result == {
        "video": "https://media.example/video-720.mp4",
        "audio": "https://media.example/audio.m4a",
    }


def test_preview_sources_skip_drm_and_non_http_formats(monkeypatch):
    from app import media_formats

    monkeypatch.setattr(
        media_formats,
        "validate_public_media_url",
        lambda url: url,
    )
    result = build_preview_sources(
        {
            "formats": [
                {
                    "url": "https://media.example/protected.mp4",
                    "protocol": "https",
                    "vcodec": "avc1",
                    "acodec": "aac",
                    "has_drm": True,
                },
                {
                    "url": "https://media.example/stream.m3u8",
                    "protocol": "m3u8_native",
                    "vcodec": "avc1",
                    "acodec": "aac",
                },
            ]
        }
    )

    assert result == {"video": None, "audio": None}


def test_preview_sources_skip_urls_rejected_by_public_address_validation(monkeypatch):
    from app import media_formats
    from app.security import URLValidationError

    def reject(_url):
        raise URLValidationError("Endereços locais ou de rede privada não são permitidos.")

    monkeypatch.setattr(media_formats, "validate_public_media_url", reject)
    result = build_preview_sources(
        {
            "formats": [
                {
                    "url": "http://127.0.0.1/private.mp4",
                    "protocol": "http",
                    "vcodec": "avc1",
                    "acodec": "aac",
                }
            ]
        }
    )

    assert result == {"video": None, "audio": None}


def test_preview_sources_use_first_available_playlist_entry(monkeypatch):
    from app import media_formats

    monkeypatch.setattr(
        media_formats,
        "validate_public_media_url",
        lambda url: url,
    )
    result = build_preview_sources(
        {
            "entries": [
                None,
                {
                    "formats": [
                        {
                            "url": "https://media.example/first.mp4",
                            "protocol": "https",
                            "vcodec": "avc1",
                            "acodec": "aac",
                        }
                    ]
                },
                {
                    "formats": [
                        {
                            "url": "https://media.example/second.mp4",
                            "protocol": "https",
                            "vcodec": "avc1",
                            "acodec": "aac",
                        }
                    ]
                },
            ]
        }
    )

    assert result == {
        "video": "https://media.example/first.mp4",
        "audio": None,
    }
