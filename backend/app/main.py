import asyncio
import json
import logging
import shutil
import threading
import time
from importlib.metadata import version
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from app.config import settings
from app.logging_config import configure_logging
from app.local_store import LocalStore
from app.security import URLValidationError, validate_url
from app.media_formats import (
    VIDEO_HEIGHTS,
    build_available_formats,
    build_preview_sources,
    platform_name,
)
from app.output_template import (
    DEFAULT_OUTPUT_TEMPLATE,
    validate_output_name,
    validate_output_template,
)
from app.task_state import (
    TERMINAL_STATUSES,
    TaskStatus,
    persist_task_state,
)

configure_logging()
logger = logging.getLogger("saveclip.api")
local_store = LocalStore(settings.database_path) if settings.standalone else None


class URLRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class DownloadRequest(URLRequest):
    format_id: str
    type: str
    items: list[str] = Field(default_factory=list, max_length=50)
    volume_percent: int = Field(default=100, ge=0, le=200)
    output_name: str | None = Field(default=None, max_length=120)


class DownloadDirectoryRequest(BaseModel):
    download_dir: str | None = Field(default=None, max_length=4096)


class OutputTemplateRequest(BaseModel):
    output_template: str = Field(min_length=1, max_length=160)


class RateLimiter:
    async def __call__(self, request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{int(time.time()) // settings.rate_limit_window_seconds}"
        if local_store is not None:
            current = await asyncio.to_thread(
                local_store.increment_rate_window,
                key,
                settings.rate_limit_window_seconds * 2,
            )
            if current > settings.rate_limit_requests:
                raise HTTPException(status_code=429, detail="Muitas requisições. Aguarde um minuto e tente novamente.")
            return
        redis = Redis.from_url(
            settings.redis_url, socket_connect_timeout=3, socket_timeout=5
        )
        key = f"saveclip:rate:{key}"
        try:
            current = await asyncio.to_thread(redis.incr, key)
            if current == 1:
                await asyncio.to_thread(redis.expire, key, settings.rate_limit_window_seconds)
            if current > settings.rate_limit_requests:
                raise HTTPException(status_code=429, detail="Muitas requisições. Aguarde um minuto e tente novamente.")
        except RedisError as exc:
            logger.error(
                "Falha ao verificar limite de requisições",
                extra={"error_type": type(exc).__name__},
            )
            raise HTTPException(status_code=503, detail="Serviço temporariamente indisponível.") from exc
        finally:
            await asyncio.to_thread(redis.close)


rate_limit = RateLimiter()
download_settings_lock = asyncio.Lock()
active_downloads: set[str] = set()
active_downloads_lock = threading.Lock()


def _redis() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5,
    )


def _set_task_state(task_id: str, **fields: object) -> None:
    persist_task_state(
        task_id,
        fields,
        local_store=local_store,
        redis_factory=_redis,
        ttl_seconds=settings.file_ttl_minutes * 60 + 300,
    )


def _get_task_state(task_id: str) -> dict[str, str]:
    if local_store is not None:
        return local_store.get_task_state(task_id)
    redis = _redis()
    try:
        return redis.hgetall(f"saveclip:task:{task_id}")
    finally:
        redis.close()


def _delete_task_state(task_id: str) -> None:
    if local_store is not None:
        local_store.delete_task(task_id)
        return
    redis = _redis()
    try:
        redis.delete(f"saveclip:task:{task_id}")
    finally:
        redis.close()


def _cleanup_expired_files() -> None:
    expiry = settings.file_ttl_minutes * 60
    now = time.time()
    if local_store is not None:
        local_store.delete_expired_terminal_tasks(now - expiry)
    roots = list(dict.fromkeys([*settings.download_dirs, settings.download_dir]))
    for root in roots:
        try:
            root.mkdir(parents=True, exist_ok=True)
            temporary_root = root / ".saveclip-temp"
            paths = (
                list(temporary_root.iterdir())
                if settings.standalone and temporary_root.is_dir()
                else ([] if settings.standalone else list(root.iterdir()))
            )
        except OSError:
            logger.exception("Falha ao acessar a pasta de downloads", extra={"path": str(root)})
            continue
        for path in paths:
            try:
                task_id = path.name
                UUID(task_id)
                if path.is_dir() and now - path.stat().st_mtime > expiry:
                    state = _get_task_state(task_id)
                    if state and state.get("status") not in TERMINAL_STATUSES:
                        continue
                    shutil.rmtree(path)
                    _delete_task_state(task_id)
            except ValueError:
                continue
            except (OSError, RedisError):
                logger.exception("Falha ao remover arquivo expirado", extra={"path": str(path)})


async def _cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_cleanup_expired_files)
        except RedisError:
            logger.exception("Falha ao limpar arquivos expirados")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    if settings.standalone:
        app.state.download_executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_downloads,
            thread_name_prefix="saveclip-download",
        )
    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    if settings.standalone:
        app.state.download_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="SaveClip API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    logger.error(
        "Erro interno não tratado",
        extra={"error_type": type(exc).__name__},
    )
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=500, content={"detail": "Erro interno. Tente novamente mais tarde."})


@app.get("/api/health")
async def health():
    if local_store is not None:
        return {
            "status": "ok",
            "storage": "sqlite",
            "yt_dlp": version("yt-dlp"),
        }
    redis = _redis()
    try:
        await asyncio.to_thread(redis.ping)
        redis_status = "ok"
    except RedisError:
        redis_status = "unavailable"
    finally:
        await asyncio.to_thread(redis.close)
    response = {
        "status": "ok" if redis_status == "ok" else "degraded",
        "redis": redis_status,
        "yt_dlp": version("yt-dlp"),
    }
    if redis_status != "ok":
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=response)
    return response


@app.get("/api/settings")
async def get_settings():
    return {
        "download_dir": str(settings.download_dir),
        "default_download_dir": str(settings.default_download_dir),
        "can_change_download_dir": settings.standalone,
        "download_dir_configured": bool(
            settings.settings_file and settings.settings_file.is_file()
        ),
        "output_template": getattr(
            settings, "output_template", DEFAULT_OUTPUT_TEMPLATE
        ),
        "max_concurrent_downloads": getattr(
            settings, "max_concurrent_downloads", 2
        ),
    }


@app.post("/api/settings/download-folder")
async def set_download_folder(payload: DownloadDirectoryRequest):
    if not settings.standalone or settings.settings_file is None:
        raise HTTPException(status_code=404, detail="A alteração da pasta só está disponível no app desktop.")

    async with download_settings_lock:
        with active_downloads_lock:
            has_active_downloads = bool(active_downloads)
        if has_active_downloads:
            raise HTTPException(
                status_code=409,
                detail="Aguarde os downloads em andamento terminarem antes de mudar a pasta.",
            )

        if payload.download_dir is None:
            target = settings.default_download_dir.resolve()
        else:
            requested = Path(payload.download_dir).expanduser()
            if not requested.is_absolute():
                raise HTTPException(status_code=422, detail="Selecione um caminho absoluto para a pasta.")
            target = requested.resolve()

        try:
            target.mkdir(parents=True, exist_ok=True)
            if not target.is_dir():
                raise OSError("O caminho selecionado não é uma pasta.")
            probe = target / f".saveclip-write-test-{uuid4()}"
            with probe.open("xb"):
                pass
            probe.unlink()
        except OSError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Não foi possível gravar na pasta selecionada: {exc}",
            ) from exc

        roots = list(dict.fromkeys(
            path.resolve()
            for path in [*settings.download_dirs, settings.download_dir, target]
        ))
        settings_file = settings.settings_file
        temporary_file = settings_file.with_suffix(".json.tmp")
        try:
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            saved_settings = (
                json.loads(settings_file.read_text(encoding="utf-8"))
                if settings_file.is_file()
                else {}
            )
            if not isinstance(saved_settings, dict):
                raise ValueError("O arquivo de configurações não contém um objeto JSON.")
            saved_settings["download_dir"] = str(target)
            saved_settings["download_dirs"] = [str(path) for path in roots]
            temporary_file.write_text(
                json.dumps(saved_settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file.replace(settings_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.exception("Não foi possível salvar as configurações de pasta")
            raise HTTPException(
                status_code=500,
                detail="Não foi possível salvar as configurações do SaveClip.",
            ) from exc

        settings.download_dir = target
        settings.download_dirs = roots
        return {
            "download_dir": str(settings.download_dir),
            "default_download_dir": str(settings.default_download_dir),
            "can_change_download_dir": True,
            "download_dir_configured": True,
        }


@app.post("/api/settings/output-template")
async def set_output_template(payload: OutputTemplateRequest):
    if not settings.standalone or settings.settings_file is None:
        raise HTTPException(
            status_code=404,
            detail="A alteração do padrão de nome só está disponível no app desktop.",
        )
    try:
        output_template = validate_output_template(payload.output_template)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async with download_settings_lock:
        settings_file = settings.settings_file
        temporary_file = settings_file.with_suffix(".json.tmp")
        try:
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            saved_settings = (
                json.loads(settings_file.read_text(encoding="utf-8"))
                if settings_file.is_file()
                else {}
            )
            if not isinstance(saved_settings, dict):
                raise ValueError("O arquivo de configurações não contém um objeto JSON.")
            saved_settings["output_template"] = output_template
            temporary_file.write_text(
                json.dumps(saved_settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file.replace(settings_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.exception("Não foi possível salvar o padrão de nome")
            raise HTTPException(
                status_code=500,
                detail="Não foi possível salvar o padrão de nome.",
            ) from exc
        settings.output_template = output_template
    return {"output_template": output_template}


@app.post("/api/info", dependencies=[Depends(rate_limit)])
async def info(payload: URLRequest):
    try:
        url = validate_url(payload.url, settings.extra_domains)
    except URLValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "playlistend": 50,
        "noplaylist": False,
        "cookiefile": None,
        "cachedir": False,
        "ignoreerrors": False,
    }
    try:
        metadata = await asyncio.to_thread(_extract_info, url, options)
    except Exception as exc:
        logger.info("Análise falhou", extra={"host": urlsplit(url).hostname})
        raise HTTPException(status_code=422, detail=_friendly_error(str(exc))) from exc

    entries = list(metadata.get("entries") or [])
    first = next((entry for entry in entries or [] if entry), None)
    source = first or metadata
    items = [
        {"id": str(index), "title": str(entry.get("title") or f"Item {index}")[:180]}
        for index, entry in enumerate(entries or [], start=1)
        if entry
    ][:50]
    return {
        "platform": platform_name(url, metadata.get("extractor_key")),
        "title": str(metadata.get("title") or source.get("title") or "Vídeo sem título")[:200],
        "author": metadata.get("uploader") or source.get("uploader") or metadata.get("channel"),
        "duration": metadata.get("duration") or source.get("duration"),
        "thumbnail": metadata.get("thumbnail") or source.get("thumbnail"),
        "formats": build_available_formats(metadata),
        "preview": build_preview_sources(metadata),
        "thumbnail_available": bool(metadata.get("thumbnail") or source.get("thumbnail")),
        "is_playlist": bool(metadata.get("_type") == "playlist" or entries),
        "items": items,
    }


def _extract_info(url: str, options: dict) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(options) as downloader:
        result = downloader.extract_info(url, download=False)
        if not result:
            raise ValueError("Conteúdo não encontrado.")
        return result


@app.post("/api/download", status_code=202, dependencies=[Depends(rate_limit)])
async def create_download(payload: DownloadRequest):
    try:
        output_name = validate_output_name(payload.output_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    valid_video = payload.type == "video" and payload.format_id in (
        {f"video_{height}" for height in VIDEO_HEIGHTS} | {"video_best"}
    )
    valid_audio = payload.type == "audio" and payload.format_id in {
        "audio_mp3",
        "audio_m4a",
        "audio_wav",
    }
    valid_thumbnail = payload.type == "thumbnail" and payload.format_id == "thumbnail"
    if not (valid_video or valid_audio or valid_thumbnail):
        raise HTTPException(status_code=422, detail="Formato de download inválido.")
    if valid_thumbnail and payload.volume_percent != 100:
        raise HTTPException(
            status_code=422,
            detail="O ajuste de volume não se aplica à miniatura.",
        )
    if (
        len(payload.items) > 50
        or len(set(payload.items)) != len(payload.items)
        or any(not item.isdigit() or not 1 <= int(item) <= 50 for item in payload.items)
    ):
        raise HTTPException(status_code=422, detail="A seleção de itens é inválida.")
    try:
        url = validate_url(payload.url, settings.extra_domains)
    except URLValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    task_id = str(uuid4())
    task_arguments = (
        task_id,
        url,
        payload.format_id,
        "thumbnail" if valid_thumbnail else payload.type,
        payload.items or None,
        str(settings.download_dir),
        getattr(settings, "output_template", DEFAULT_OUTPUT_TEMPLATE),
        payload.volume_percent,
        output_name if not valid_thumbnail else None,
    )
    if local_store is not None:
        async with download_settings_lock:
            with active_downloads_lock:
                active_downloads.add(task_id)
            try:
                _set_task_state(
                    task_id,
                    status=TaskStatus.QUEUED.value,
                    percent=0,
                    url=url,
                    created_at=time.time(),
                    download_dir=str(settings.download_dir),
                    items=payload.items or [],
                )
                app.state.download_executor.submit(_run_local_download, *task_arguments)
            except Exception:
                with active_downloads_lock:
                    active_downloads.discard(task_id)
                raise
        return {"task_id": task_id, "status": "queued"}

    redis = _redis()
    queue_connection = Redis.from_url(
        settings.redis_url, socket_connect_timeout=3, socket_timeout=5
    )
    try:
        await asyncio.to_thread(
            redis.hset,
            f"saveclip:task:{task_id}",
            mapping={
                "status": TaskStatus.QUEUED.value,
                "percent": "0",
                "url": url,
                "created_at": str(time.time()),
                "items": json.dumps(payload.items or []),
            },
        )
        queue = Queue("downloads", connection=queue_connection)
        await asyncio.to_thread(
            queue.enqueue,
            "app.tasks.download_task",
            task_id,
            url,
            payload.format_id,
            "thumbnail" if valid_thumbnail else payload.type,
            payload.items or None,
            str(settings.download_dir),
            getattr(settings, "output_template", DEFAULT_OUTPUT_TEMPLATE),
            payload.volume_percent,
            output_name if not valid_thumbnail else None,
            job_id=task_id,
            job_timeout=60 * 60,
            result_ttl=settings.file_ttl_minutes * 60,
            failure_ttl=settings.file_ttl_minutes * 60,
        )
    except RedisError as exc:
        logger.error(
            "Não foi possível enfileirar download",
            extra={"error_type": type(exc).__name__},
        )
        await asyncio.to_thread(redis.delete, f"saveclip:task:{task_id}")
        raise HTTPException(status_code=503, detail="Fila de downloads indisponível.") from exc
    finally:
        await asyncio.to_thread(redis.close)
        await asyncio.to_thread(queue_connection.close)
    return {"task_id": task_id, "status": "queued"}


@app.post("/api/download/{task_id}/cancel", dependencies=[Depends(rate_limit)])
async def cancel_download(task_id: str):
    try:
        task_id = str(UUID(task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.") from exc
    for _ in range(3):
        state = await asyncio.to_thread(_get_task_state, task_id)
        if not state:
            raise HTTPException(status_code=404, detail="Tarefa não encontrada ou expirada.")

        current = state.get("status")
        if current in TERMINAL_STATUSES:
            if current == TaskStatus.CANCELLED.value:
                return {"task_id": task_id, "status": current}
            raise HTTPException(status_code=409, detail="A tarefa já foi finalizada.")
        if current == TaskStatus.CANCEL_REQUESTED.value:
            return {"task_id": task_id, "status": current}
        next_status = (
            TaskStatus.CANCELLED.value
            if current == TaskStatus.QUEUED.value
            else TaskStatus.CANCEL_REQUESTED.value
        )
        try:
            await asyncio.to_thread(
                _set_task_state,
                task_id,
                status=next_status,
                error="",
            )
            return {"task_id": task_id, "status": next_status}
        except ValueError:
            continue
    raise HTTPException(
        status_code=409,
        detail="O estado da tarefa mudou durante o cancelamento. Tente novamente.",
    )


def _run_local_download(
    task_id: str,
    url: str,
    format_id: str,
    media_type: str,
    selected_items: list[str] | None,
    download_dir: str,
    output_template: str,
    volume_percent: int = 100,
    output_name: str | None = None,
) -> None:
    from app.tasks import _error_message, download_task

    try:
        download_task(
            task_id,
            url,
            format_id,
            media_type,
            selected_items,
            download_dir,
            output_template,
            volume_percent,
            output_name,
        )
    except Exception as exc:
        logger.error(
            "Download local falhou",
            extra={"task_id": task_id, "error_type": type(exc).__name__},
        )
        state = _get_task_state(task_id)
        if state.get("status") in {
            TaskStatus.CANCEL_REQUESTED.value,
            TaskStatus.CANCELLED.value,
        }:
            _set_task_state(task_id, status=TaskStatus.CANCELLED.value)
        else:
            _set_task_state(
                task_id,
                status=TaskStatus.FAILED.value,
                error=_error_message(str(exc)),
            )
    finally:
        with active_downloads_lock:
            active_downloads.discard(task_id)


@app.get("/api/progress/{task_id}", dependencies=[Depends(rate_limit)])
async def progress(task_id: str, request: Request):
    try:
        task_id = str(UUID(task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.") from exc

    async def events():
        while True:
            if await request.is_disconnected():
                break
            state = await asyncio.to_thread(_get_task_state, task_id)
            if not state:
                yield "event: error\ndata: {\"detail\":\"Tarefa não encontrada ou expirada.\"}\n\n"
                break
            event = {
                key: (
                    json.loads(value)
                    if key in {"error", "filename", "file_path", "title"}
                    and value.startswith(("{", "["))
                    else value
                )
                for key, value in state.items()
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if state.get("status") in TERMINAL_STATUSES:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _completed_output(task_id: str) -> tuple[dict[str, str], Path]:
    try:
        task_id = str(UUID(task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.") from exc
    state = await asyncio.to_thread(_get_task_state, task_id)
    output_path = Path(state.get("file_path", ""))
    download_dir = Path(state.get("download_dir", ""))
    expected_parent = download_dir if settings.standalone else download_dir / task_id
    if (
        state.get("status") != TaskStatus.COMPLETED.value
        or output_path.resolve().parent != expected_parent.resolve()
        or not (output_path.is_file() or output_path.is_dir())
    ):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado ou expirado.")
    return state, output_path


@app.get("/api/files/{task_id}", dependencies=[Depends(rate_limit)])
async def get_playlist_files(task_id: str):
    _, output_path = await _completed_output(task_id)
    if not output_path.is_dir():
        raise HTTPException(status_code=404, detail="Pasta da playlist não encontrada.")
    return {
        "files": [
            {"name": path.name}
            for path in sorted(output_path.iterdir(), key=lambda item: item.name.casefold())
            if path.is_file() and path.resolve().parent == output_path.resolve()
        ]
    }


@app.get("/api/file/{task_id}/item", dependencies=[Depends(rate_limit)])
async def get_playlist_file(task_id: str, filename: str):
    _, output_path = await _completed_output(task_id)
    if (
        not output_path.is_dir()
        or not filename
        or Path(filename).name != filename
    ):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado ou expirado.")
    file_path = output_path / filename
    if (
        file_path.resolve().parent != output_path.resolve()
        or not file_path.is_file()
    ):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado ou expirado.")
    return FileResponse(file_path, filename=file_path.name)


@app.get("/api/file/{task_id}", dependencies=[Depends(rate_limit)])
async def get_file(task_id: str):
    state, file_path = await _completed_output(task_id)
    if not file_path.is_file():
        raise HTTPException(status_code=409, detail="Este download contém uma pasta de arquivos.")
    return FileResponse(
        file_path,
        filename=state.get("filename", file_path.name),
        media_type="application/octet-stream",
    )


def _friendly_error(message: str) -> str:
    lowered = message.lower()
    if "private" in lowered or "sign in" in lowered or "login" in lowered:
        return "Conteúdo privado ou que exige login. O SaveClip não aceita cookies nem tenta contornar controles de acesso."
    if "403" in lowered or "forbidden" in lowered:
        return "A plataforma recusou o acesso. O conteúdo pode ser privado ou exigir uma permissão que o SaveClip não contorna."
    if "429" in lowered or "too many requests" in lowered:
        return "A plataforma limitou temporariamente as solicitações. Aguarde e tente novamente."
    if "404" in lowered:
        return "O conteúdo não foi encontrado. Ele pode ter sido removido ou o link pode estar incorreto."
    if "age" in lowered or "age-restricted" in lowered:
        return "Conteúdo com restrição de idade. O SaveClip não tenta contornar essa restrição."
    if "drm" in lowered:
        return "Conteúdo protegido por DRM não é suportado."
    if "removed" in lowered or "not available" in lowered or "unavailable" in lowered:
        return "Conteúdo removido ou indisponível nesta plataforma."
    if "unsupported url" in lowered or "no suitable extractor" in lowered:
        return "Plataforma não suportada. Confira o endereço e tente novamente."
    return "Não foi possível analisar este link. Ele pode ser inválido, privado, removido ou incompatível."


if settings.standalone and settings.frontend_dir and settings.frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
