import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from redis import Redis

from app.config import settings
from app.logging_config import configure_logging
from app.local_store import LocalStore
from app.security import validate_url
from app.output_template import (
    DEFAULT_OUTPUT_TEMPLATE,
    to_yt_dlp_template,
    validate_output_name,
)
from app.task_state import TaskStatus, persist_task_state
from app.media_formats import VIDEO_HEIGHTS

configure_logging()
logger = logging.getLogger("saveclip.tasks")
local_store = LocalStore(settings.database_path) if settings.standalone else None


class DownloadCancelled(Exception):
    pass


class OutputVolumeError(RuntimeError):
    pass


def _redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _get_task_state(task_id: str) -> dict[str, str]:
    if local_store is not None:
        return local_store.get_task_state(task_id)
    client = _redis()
    try:
        return client.hgetall(f"saveclip:task:{task_id}")
    finally:
        client.close()


def _update_state(task_id: str, **fields: object) -> None:
    persist_task_state(
        task_id,
        fields,
        local_store=local_store,
        redis_factory=_redis,
        ttl_seconds=settings.file_ttl_minutes * 60 + 300,
    )


def _max_height(format_id: str) -> int:
    match = re.fullmatch(r"video_(360|480|720|1080|2160)", format_id)
    if not match:
        raise ValueError("Qualidade de vídeo inválida.")
    return int(match.group(1))


def _progress_hook(task_id: str, download_dir: Path):
    def update(data: dict) -> None:
        state = _get_task_state(task_id)
        if state.get("status") in {
            TaskStatus.CANCEL_REQUESTED.value,
            TaskStatus.CANCELLED.value,
        }:
            _update_state(task_id, status=TaskStatus.CANCELLED.value)
            raise DownloadCancelled("Download cancelado pelo usuário.")
        if download_dir.exists():
            os.utime(download_dir, None)
        if data.get("status") == "downloading":
            received = int(data.get("downloaded_bytes") or 0)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            if received > settings.max_file_size_bytes or total > settings.max_file_size_bytes:
                raise ValueError("O arquivo excede o limite de tamanho configurado.")
            _update_state(
                task_id,
                status="downloading",
                percent=round(received / total * 100, 1) if total else 0,
                received=received,
                total=total,
                speed=int(data.get("speed") or 0),
            )
        elif data.get("status") == "finished":
            _update_state(task_id, status="processing", percent=99)

    return update


def _sanitize_title(title: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    return clean[:160] or "saveclip"


def _validate_task_id(task_id: str) -> str:
    return str(UUID(task_id))


def _process_output_volume(
    file_path: Path,
    media_type: str,
    volume_percent: int,
    ffmpeg_path: str,
    task_id: str,
) -> None:
    if volume_percent == 100 or media_type not in {"audio", "video"}:
        return

    temporary_path = file_path.with_name(
        f".{file_path.stem}.saveclip-{UUID(task_id).hex}.tmp{file_path.suffix}"
    )
    arguments = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(file_path),
    ]
    if media_type == "video":
        arguments.extend(["-map", "0:v:0?", "-map", "0:a?"])
        arguments.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"])
    else:
        arguments.extend(["-map", "0:a:0"])
        codec = {
            ".mp3": "libmp3lame",
            ".m4a": "aac",
            ".wav": "pcm_s16le",
        }.get(file_path.suffix.lower())
        if not codec:
            raise OutputVolumeError("Formato de áudio não suportado para ajuste de volume.")
        arguments.extend(["-c:a", codec])
        if codec != "pcm_s16le":
            arguments.extend(["-b:a", "192k"])
    arguments.extend(
        [
            "-map_metadata",
            "0",
            "-af",
            f"volume={volume_percent / 100:.2f}",
            str(temporary_path),
        ]
    )

    process = None
    try:
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        while True:
            try:
                _, error_output = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                try:
                    output_too_large = (
                        temporary_path.exists()
                        and temporary_path.stat().st_size > settings.max_file_size_bytes
                    )
                except OSError:
                    output_too_large = False
                if output_too_large:
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise OutputVolumeError(
                        "O arquivo excede o limite de tamanho configurado."
                    )
                state = _get_task_state(task_id)
                if state.get("status") in {
                    TaskStatus.CANCEL_REQUESTED.value,
                    TaskStatus.CANCELLED.value,
                }:
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise DownloadCancelled("Ajuste de volume cancelado.")
        if process.returncode != 0:
            detail = (error_output or "").strip()[-2000:]
            logger.error(
                "Falha ao ajustar volume do arquivo",
                extra={
                    "task_id": task_id,
                    "output_filename": file_path.name,
                    "error_type": "FFmpeg",
                    "technical_detail": detail,
                },
            )
            raise OutputVolumeError("Não foi possível ajustar o volume do arquivo.")
        if not temporary_path.is_file():
            raise OutputVolumeError("O FFmpeg não gerou o arquivo com o volume ajustado.")
        if temporary_path.stat().st_size > settings.max_file_size_bytes:
            raise OutputVolumeError("O arquivo excede o limite de tamanho configurado.")
        os.replace(temporary_path, file_path)
    except OSError as exc:
        logger.error(
            "Não foi possível iniciar o ajuste de volume",
            extra={
                "task_id": task_id,
                "output_filename": file_path.name,
                "error_type": type(exc).__name__,
            },
        )
        raise OutputVolumeError(
            "Não foi possível ajustar o volume do arquivo. Verifique a instalação do FFmpeg."
        ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def download_task(
    task_id: str,
    url: str,
    format_id: str,
    media_type: str,
    selected_items: list[str] | None = None,
    download_dir: str | Path | None = None,
    output_template: str | None = None,
    volume_percent: int = 100,
    output_name: str | None = None,
) -> str:
    import yt_dlp

    task_id = _validate_task_id(task_id)
    if isinstance(volume_percent, bool) or not isinstance(volume_percent, int) or not 0 <= volume_percent <= 200:
        raise ValueError("O volume deve estar entre 0% e 200%.")
    url = validate_url(url, settings.extra_domains)
    state = _get_task_state(task_id)
    if state.get("status") == TaskStatus.CANCELLED.value:
        return ""
    if state.get("status") == TaskStatus.CANCEL_REQUESTED.value:
        _update_state(task_id, status=TaskStatus.CANCELLED.value)
        return ""
    _update_state(task_id, status=TaskStatus.ANALYZING.value, percent=0)
    root_dir = Path(download_dir) if download_dir else settings.download_dir
    if settings.standalone:
        temporary_root = root_dir / ".saveclip-temp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            import ctypes

            if not ctypes.windll.kernel32.SetFileAttributesW(
                str(temporary_root), 0x02
            ):
                raise OSError("Não foi possível ocultar a pasta temporária do SaveClip.")
        destination = temporary_root / task_id
    else:
        destination = root_dir / task_id
    destination.mkdir(parents=True, exist_ok=True)
    _update_state(
        task_id,
        received=0,
        total=0,
        error="",
        download_dir=str(root_dir),
    )

    def progress(data: dict) -> None:
        if data.get("info_dict", {}).get("duration", 0) > settings.max_duration_seconds:
            raise ValueError("O conteúdo excede o limite de duração configurado.")
        _progress_hook(task_id, destination)(data)

    requested_output_name = validate_output_name(output_name)
    configured_output_template = (
        output_template
        or getattr(settings, "output_template", DEFAULT_OUTPUT_TEMPLATE)
    )
    use_custom_media_name = not (selected_items and len(selected_items) > 1)
    media_output_template = to_yt_dlp_template(
        configured_output_template,
        requested_output_name if use_custom_media_name else None,
    )
    output = str(destination / media_output_template)
    common = {
        "outtmpl": output,
        "noplaylist": not bool(selected_items),
        "playlist_items": ",".join(selected_items) if selected_items else None,
        "restrictfilenames": not (requested_output_name and use_custom_media_name),
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "cookiefile": None,
        "cachedir": False,
        "max_filesize": settings.max_file_size_bytes,
        "match_filter": lambda info, *, incomplete: (
            "Conteúdo protegido por DRM não é suportado."
            if info.get("has_drm")
            else (
                "O conteúdo excede o limite de duração configurado."
                if (info.get("duration") or 0) > settings.max_duration_seconds
                else None
            )
        ),
        "progress_hooks": [progress],
    }
    if settings.standalone:
        import imageio_ffmpeg

        common["ffmpeg_location"] = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_path = common.get("ffmpeg_location") or shutil.which("ffmpeg")

    if media_type == "thumbnail":
        common["writethumbnail"] = True
        common["skip_download"] = True
    elif media_type == "audio":
        if format_id not in {"audio_mp3", "audio_m4a", "audio_wav"}:
            raise ValueError("Formato de áudio inválido.")
        common["format"] = "bestaudio/best"
        common["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": {
                    "audio_mp3": "mp3",
                    "audio_m4a": "m4a",
                    "audio_wav": "wav",
                }[format_id],
                "preferredquality": "192",
            }
        ]
    elif media_type == "video":
        if format_id == "video_best":
            common["format"] = "bestvideo+bestaudio/best"
        else:
            height = _max_height(format_id)
            common["format"] = (
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]"
            )
        common["merge_output_format"] = "mp4"
    else:
        raise ValueError("Tipo de download inválido.")

    try:
        with yt_dlp.YoutubeDL(common) as downloader:
            result = downloader.extract_info(url, download=True)
            if not result:
                raise ValueError("Não foi possível obter o conteúdo.")
    except DownloadCancelled:
        if _get_task_state(task_id).get("status") != TaskStatus.CANCELLED.value:
            _update_state(task_id, status=TaskStatus.CANCELLED.value)
        return ""
    except Exception as exc:
        if _get_task_state(task_id).get("status") in {
            TaskStatus.CANCEL_REQUESTED.value,
            TaskStatus.CANCELLED.value,
        }:
            _update_state(task_id, status=TaskStatus.CANCELLED.value)
            return ""
        _update_state(
            task_id,
            status=TaskStatus.FAILED.value,
            error=_error_message(str(exc)),
        )
        raise

    state = _get_task_state(task_id)
    if state.get("status") == TaskStatus.CANCEL_REQUESTED.value:
        _update_state(task_id, status=TaskStatus.CANCELLED.value)
        return ""
    _update_state(task_id, status=TaskStatus.PROCESSING.value, percent=99)

    files = [
        path
        for path in destination.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not files:
        _update_state(
            task_id,
            status=TaskStatus.FAILED.value,
            error="A plataforma não forneceu um arquivo para download.",
        )
        raise ValueError("Nenhum arquivo final foi gerado.")

    if media_type in {"audio", "video"} and volume_percent != 100:
        if not ffmpeg_path:
            raise OutputVolumeError(
                "Não foi possível ajustar o volume do arquivo. Verifique a instalação do FFmpeg."
            )
        try:
            for path in files:
                _process_output_volume(
                    path,
                    media_type,
                    volume_percent,
                    ffmpeg_path,
                    task_id,
                )
        except DownloadCancelled:
            _update_state(task_id, status=TaskStatus.CANCELLED.value)
            return ""
        except OutputVolumeError as exc:
            _update_state(
                task_id,
                status=TaskStatus.FAILED.value,
                error=str(exc),
            )
            raise

    if selected_items:
        folder_name = requested_output_name or _sanitize_title(
            str(result.get("title") or "saveclip")
        )
        if re.match(
            r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",
            folder_name,
            re.IGNORECASE,
        ):
            folder_name = f"_{folder_name}"
        playlist_folder = destination / folder_name
        folder_index = 2
        while playlist_folder.exists():
            playlist_folder = destination / f"{folder_name} ({folder_index})"
            folder_index += 1
        playlist_folder.mkdir()
        for path in files:
            shutil.move(str(path), str(playlist_folder / path.name))
        file_path = playlist_folder
        output_size = sum(path.stat().st_size for path in playlist_folder.iterdir())
    else:
        file_path = files[0]
        output_size = file_path.stat().st_size

    if output_size > settings.max_file_size_bytes:
        shutil.rmtree(destination, ignore_errors=True)
        _update_state(
            task_id,
            status=TaskStatus.FAILED.value,
            error="O arquivo excede o limite de tamanho configurado.",
        )
        raise ValueError("O arquivo excede o limite de tamanho configurado.")

    if settings.standalone:
        if file_path.is_dir():
            folder_name = file_path.name
            final_path = root_dir / folder_name
            index = 2
            while final_path.exists():
                final_path = root_dir / f"{folder_name} ({index})"
                index += 1
        else:
            final_path = root_dir / file_path.name
            suffix = file_path.suffix
            stem = file_path.stem
            index = 2
            while final_path.exists():
                final_path = root_dir / f"{stem} ({index}){suffix}"
                index += 1
        file_path = Path(shutil.move(str(file_path), str(final_path)))
        shutil.rmtree(destination)

    _update_state(
        task_id,
        status=TaskStatus.COMPLETED.value,
        percent=100,
        filename=file_path.name,
        file_path=str(file_path),
        title=_sanitize_title(str(result.get("title") or file_path.stem)),
        size=output_size,
    )
    logger.info(
        "Download concluído",
        extra={"task_id": task_id, "output_filename": file_path.name},
    )
    return str(file_path)


def _error_message(message: str) -> str:
    lower = message.lower()
    if "ajustar o volume" in lower:
        return message
    if "excede o limite de tamanho" in lower:
        return "O arquivo excede o limite de tamanho configurado."
    if "private" in lower or "sign in" in lower or "login" in lower:
        return "Conteúdo privado ou que exige login. O SaveClip não aceita cookies nem tenta contornar controles de acesso."
    if "403" in lower or "forbidden" in lower:
        return "A plataforma recusou o acesso. O conteúdo pode ser privado ou exigir uma permissão que o SaveClip não contorna."
    if "429" in lower or "too many requests" in lower:
        return "A plataforma limitou temporariamente as solicitações. Aguarde e tente novamente."
    if "404" in lower:
        return "O conteúdo não foi encontrado. Ele pode ter sido removido ou o link pode estar incorreto."
    if "age" in lower or "age-restricted" in lower:
        return "Conteúdo com restrição de idade. O SaveClip não tenta contornar essa restrição."
    if "drm" in lower:
        return "Conteúdo protegido por DRM não é suportado."
    if "removed" in lower or "not available" in lower or "unavailable" in lower:
        return "Conteúdo removido ou indisponível nesta plataforma."
    if "unsupported url" in lower or "no suitable extractor" in lower:
        host = urlsplit(message).hostname if "://" in message else None
        return f"Plataforma não suportada{f' ({host})' if host else ''}."
    return "Não foi possível baixar este conteúdo. Verifique o link, as permissões e tente novamente."
