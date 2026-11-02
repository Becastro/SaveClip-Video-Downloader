import json
import os
import logging
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from app.output_template import DEFAULT_OUTPUT_TEMPLATE, validate_output_template


HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def _download_settings(app_data: Path) -> tuple[Path, Path, Path, list[Path]]:
    default_downloads = app_data / "downloads"
    settings_file = app_data / "settings.json"
    download_dirs = [default_downloads]
    downloads = default_downloads
    if settings_file.exists():
        saved_settings = json.loads(settings_file.read_text(encoding="utf-8"))
        configured_dir = Path(saved_settings["download_dir"])
        if not configured_dir.is_absolute():
            raise ValueError("O caminho salvo para downloads não é absoluto.")
        downloads = configured_dir
        saved_dirs = saved_settings.get("download_dirs", [])
        if not isinstance(saved_dirs, list) or not all(
            isinstance(path, str) and Path(path).is_absolute()
            for path in saved_dirs
        ):
            raise ValueError("A lista de pastas salvas é inválida.")
        download_dirs.extend(Path(path) for path in saved_dirs)
    downloads = downloads.resolve()
    download_dirs.append(downloads)
    return (
        settings_file,
        default_downloads.resolve(),
        downloads,
        list(dict.fromkeys(path.resolve() for path in download_dirs)),
    )


class DesktopApi:
    def select_download_folder(self):
        import webview

        selected = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return selected[0] if selected else None

    def open_in_browser(self, raw_url: str) -> bool:
        import webbrowser

        from app.config import settings
        from app.security import validate_url

        url = validate_url(raw_url, settings.extra_domains)
        return webbrowser.open(url, new=2)

    def open_download_location(self, raw_task_id: str) -> bool:
        import subprocess
        from uuid import UUID

        from app.main import TaskStatus, _get_task_state, settings

        try:
            task_id = str(UUID(raw_task_id))
        except ValueError as exc:
            raise ValueError("Tarefa de download inválida.") from exc

        state = _get_task_state(task_id)
        if state.get("status") != TaskStatus.COMPLETED.value:
            raise ValueError("O arquivo concluído não está mais disponível.")

        download_dir = Path(state.get("download_dir", "")).resolve()
        file_path = Path(state.get("file_path", "")).resolve()
        expected_parent = download_dir if settings.standalone else download_dir / task_id
        if (
            file_path.parent != expected_parent.resolve()
            or not (file_path.is_file() or file_path.is_dir())
        ):
            raise ValueError("O download concluído não foi encontrado na pasta de downloads.")

        if file_path.is_dir():
            subprocess.Popen(["explorer.exe", str(file_path)])
        else:
            subprocess.Popen(["explorer.exe", "/select,", str(file_path)])
        return True


def _show_message(message: str) -> None:
    logging.getLogger("saveclip.launcher").error(message)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "SaveClip", 0x10)
        except (AttributeError, OSError):
            pass


def _healthcheck() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=1) as response:
            return response.status == 200 and b'"status":"ok"' in response.read()
    except (OSError, urllib.error.URLError):
        return False


def _wait_for_server(server_thread: threading.Thread) -> bool:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if _healthcheck():
            return True
        if not server_thread.is_alive():
            return False
        time.sleep(0.25)
    return False


def main() -> int:
    if _healthcheck():
        _show_message(
            "O SaveClip já está aberto.\n"
            "Para abri-lo na janela desktop, feche a versão antiga e inicie novamente."
        )
        return 1

    with socket.socket() as check:
        if check.connect_ex((HOST, PORT)) == 0:
            _show_message(f"A porta {PORT} já está em uso. Feche o outro programa e tente novamente.")
            return 1

    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)
    else:
        bundle_dir = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(bundle_dir / "backend"))

    frontend_dir = (
        bundle_dir / "frontend_dist"
        if getattr(sys, "frozen", False)
        else bundle_dir / "frontend" / "dist"
    )
    if not (frontend_dir / "index.html").is_file():
        _show_message("Interface do SaveClip não encontrada. Execute Build-SaveClip.bat primeiro.")
        return 1

    app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "SaveClip"
    app_data.mkdir(parents=True, exist_ok=True)
    try:
        settings_file, default_downloads, downloads, download_dirs = _download_settings(app_data)
        saved_settings = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.is_file() else {}
        output_template = validate_output_template(
            saved_settings.get("output_template", DEFAULT_OUTPUT_TEMPLATE)
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        _show_message(f"Não foi possível ler as configurações do SaveClip.\n\nDetalhes: {exc}")
        return 1
    try:
        for directory in download_dirs:
            directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _show_message(
            "Não foi possível acessar a pasta de downloads configurada. "
            "Verifique se a unidade está conectada e tente novamente.\n\n"
            f"Detalhes: {exc}"
        )
        return 1
    logging.basicConfig(
        filename=app_data / "saveclip.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    logger = logging.getLogger("saveclip.launcher")

    os.environ.update(
        {
            "SAVECLIP_STANDALONE": "true",
            "SAVECLIP_FRONTEND_DIR": str(frontend_dir),
            "SAVECLIP_DATABASE": str(app_data / "saveclip.db"),
            "DOWNLOAD_DIR": str(downloads),
            "SAVECLIP_DEFAULT_DOWNLOAD_DIR": str(default_downloads.resolve()),
            "SAVECLIP_DOWNLOAD_DIRS": json.dumps([str(path) for path in download_dirs]),
            "SAVECLIP_SETTINGS_FILE": str(settings_file),
            "OUTPUT_TEMPLATE": output_template,
            "CORS_ORIGINS": URL,
            "LOG_LEVEL": "INFO",
        }
    )

    try:
        import webview
        import uvicorn

        from app.main import app
    except Exception as exc:
        _show_message(
            "Não foi possível carregar os componentes do SaveClip desktop. "
            f"Execute Build-SaveClip.bat novamente.\n\nDetalhes: {exc}"
        )
        return 1

    logger.info("Iniciando janela desktop", extra={"path": str(downloads)})

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(
        target=server.run, name="saveclip-api", daemon=True
    )
    server_thread.start()
    if not _wait_for_server(server_thread):
        server.should_exit = True
        _show_message("O servidor local do SaveClip não iniciou. Consulte os logs e tente novamente.")
        return 1

    try:
        webview.create_window(
            "SaveClip",
            URL,
            width=960,
            height=700,
            min_size=(720, 540),
            background_color="#17191b",
            js_api=DesktopApi(),
        )
        webview.start(gui="edgechromium", debug=False)
    except Exception as exc:
        server.should_exit = True
        _show_message(
            "Não foi possível abrir a janela do SaveClip. Verifique se o "
            "Microsoft Edge WebView2 Runtime está instalado.\n\n"
            f"Detalhes: {exc}"
        )
        return 1
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
