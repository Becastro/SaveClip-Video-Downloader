from app.security import URLValidationError, validate_public_media_url


VIDEO_HEIGHTS = (360, 480, 720, 1080, 2160)
AUDIO_FORMATS = (
    {"format_id": "audio_mp3", "type": "audio", "label": "MP3"},
    {"format_id": "audio_m4a", "type": "audio", "label": "M4A"},
    {"format_id": "audio_wav", "type": "audio", "label": "WAV"},
)


def build_available_formats(metadata: dict) -> list[dict[str, str]]:
    entries = list(metadata.get("entries") or [])
    source = next((entry for entry in entries if entry), None) or metadata
    formats = source.get("formats") or []
    usable = [fmt for fmt in formats if not fmt.get("has_drm")]
    extractor = str(
        source.get("extractor_key")
        or metadata.get("extractor_key")
        or source.get("extractor")
        or metadata.get("extractor")
        or ""
    ).lower()
    is_twitter = extractor in {"twitter", "twittercard"}
    has_video = any(
        fmt.get("vcodec") not in {None, "none"} for fmt in usable
    ) or (
        is_twitter
        and any(
            str(fmt.get("format_id") or "").startswith("http")
            and fmt.get("url")
            for fmt in usable
        )
    )
    has_audio = any(
        fmt.get("acodec") not in {None, "none"} for fmt in usable
    )
    if not has_audio and has_video and is_twitter:
        has_audio = True

    heights = {
        int(fmt["height"])
        for fmt in usable
        if fmt.get("height")
        and fmt.get("vcodec") not in {None, "none"}
    }
    result = [
        {"format_id": f"video_{height}", "type": "video", "label": f"{height}p"}
        for height in VIDEO_HEIGHTS
        if height in heights
    ]
    if has_video:
        result.append(
            {"format_id": "video_best", "type": "video", "label": "Melhor qualidade"}
        )
    if has_audio:
        result.extend(AUDIO_FORMATS)
    return result


def build_preview_sources(metadata: dict) -> dict[str, str | None]:
    entries = list(metadata.get("entries") or [])
    source = next((entry for entry in entries if entry), None) or metadata
    formats = list(source.get("formats") or [])
    extractor = str(
        source.get("extractor_key")
        or metadata.get("extractor_key")
        or source.get("extractor")
        or metadata.get("extractor")
        or ""
    ).lower()

    def numeric(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0

    def playable_url(media_type: str) -> str | None:
        candidates = []
        for item in formats or [source]:
            url = item.get("url")
            protocol = str(item.get("protocol") or "").lower()
            if (
                not url
                or item.get("has_drm")
                or protocol not in {"", "http", "https"}
            ):
                continue
            has_video = item.get("vcodec") not in {None, "none"}
            has_audio = item.get("acodec") not in {None, "none"}
            if media_type == "video":
                is_twitter_stream = (
                    extractor in {"twitter", "twittercard"}
                    and str(item.get("format_id") or "").startswith("http")
                )
                if not (has_video and has_audio) and not is_twitter_stream:
                    continue
            elif not has_audio or has_video:
                continue
            candidates.append(item)

        candidates.sort(
            key=lambda item: (
                numeric(item.get("quality")),
                numeric(item.get("height")),
                numeric(item.get("tbr") or item.get("abr")),
                numeric(item.get("filesize") or item.get("filesize_approx")),
            ),
            reverse=True,
        )
        for item in candidates:
            try:
                return validate_public_media_url(str(item["url"]))
            except URLValidationError:
                continue
        return None

    return {
        "video": playable_url("video"),
        "audio": playable_url("audio"),
    }


def platform_name(url: str, extractor_key: str | None) -> str:
    platform = extractor_key
    if platform and platform.lower() != "generic":
        return platform
    return platform or "Plataforma suportada"
