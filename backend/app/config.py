import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.output_template import DEFAULT_OUTPUT_TEMPLATE, validate_output_template


def _domains(value: str) -> frozenset[str]:
    return frozenset(
        domain.strip().lower().lstrip(".")
        for domain in value.split(",")
        if domain.strip()
    )


def _concurrency_limit(value: str) -> int:
    return min(4, max(1, int(value)))


@dataclass
class Settings:
    standalone: bool = os.getenv("SAVECLIP_STANDALONE", "").lower() == "true"
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    download_dir: Path = Path(
        os.getenv("DOWNLOAD_DIR", str(Path.cwd() / "downloads"))
    )
    default_download_dir: Path = Path(
        os.getenv(
            "SAVECLIP_DEFAULT_DOWNLOAD_DIR",
            os.getenv("DOWNLOAD_DIR", str(Path.cwd() / "downloads")),
        )
    )
    download_dirs: list[Path] = field(
        default_factory=lambda: [
            Path(path)
            for path in json.loads(os.getenv("SAVECLIP_DOWNLOAD_DIRS", "[]"))
        ]
    )
    settings_file: Path | None = (
        Path(os.environ["SAVECLIP_SETTINGS_FILE"])
        if os.getenv("SAVECLIP_SETTINGS_FILE")
        else None
    )
    max_duration_seconds: int = int(os.getenv("MAX_DURATION_SECONDS", "7200"))
    max_file_size_bytes: int = int(os.getenv("MAX_FILE_SIZE_BYTES", str(2 * 1024**3)))
    max_concurrent_downloads: int = _concurrency_limit(
        os.getenv("MAX_CONCURRENT_DOWNLOADS", "2")
    )
    output_template: str = validate_output_template(
        os.getenv("OUTPUT_TEMPLATE", DEFAULT_OUTPUT_TEMPLATE)
    )
    file_ttl_minutes: int = int(os.getenv("FILE_TTL_MINUTES", "25"))
    rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    )
    extra_domains: frozenset[str] = _domains(os.getenv("EXTRA_ALLOWED_DOMAINS", ""))
    database_path: Path = Path(
        os.getenv("SAVECLIP_DATABASE", str(Path.cwd() / "saveclip.db"))
    )
    frontend_dir: Path | None = (
        Path(os.getenv("SAVECLIP_FRONTEND_DIR", ""))
        if os.getenv("SAVECLIP_STANDALONE", "").lower() == "true"
        else None
    )


settings = Settings()
