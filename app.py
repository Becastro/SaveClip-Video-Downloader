"""Local, dependency-free direct media downloader."""
from __future__ import annotations

import http.server
import ipaddress
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path.home() / ".video-downloader"
DATA.mkdir(exist_ok=True)
CONFIG_PATH = DATA / "settings.json"
HISTORY_PATH = DATA / "history.json"
lock = threading.RLock()
jobs: dict[str, dict] = {}

def settings():
    try: return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {"folder": str(Path.home() / "Downloads")}

def save_settings(value):
    CONFIG_PATH.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def history():
    try: return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError): return []

def save_history(items): HISTORY_PATH.write_text(json.dumps(items[:100], ensure_ascii=False, indent=2), encoding="utf-8")

def safe_url(raw):
    try: parsed = urllib.parse.urlsplit(raw.strip())
    except ValueError: raise ValueError("O endereço informado não é válido.")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Informe um endereço HTTP ou HTTPS direto para um arquivo de mídia.")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Endereços locais não são permitidos.")
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not addresses: raise ValueError("Não foi possível localizar o servidor.")
        for info in addresses:
            address = ipaddress.ip_address(info[4][0])
            if not address.is_global: raise ValueError("Por segurança, endereços de rede local não são permitidos.")
    except socket.gaierror: raise ValueError("Não foi possível localizar o servidor do link.")
    return urllib.parse.urlunsplit(parsed)

def platform_advice(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    host = host.lower().removeprefix("www.")
    if host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be":
        return "Links do YouTube não são arquivos diretos. Baixe vídeos próprios pelo YouTube Studio/Google Takeout ou use o recurso oficial de downloads offline do Premium."
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "Use Compartilhar → Salvar vídeo no TikTok. O salvamento depende da permissão definida pelo criador."
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Para conteúdo próprio, use a opção oficial de baixar suas informações no Instagram. Links de Reels não são arquivos diretos."
    return None

def filename_from(response, url):
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", disposition, re.I)
    name = urllib.parse.unquote(next((x for x in match.groups() if x), "")) if match else ""
    if not name: name = Path(urllib.parse.unquote(urllib.parse.urlsplit(response.geturl()).path)).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:180]
    if not name: name = "video-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    if not Path(name).suffix:
        name += mimetypes.guess_extension(response.headers.get_content_type()) or ".mp4"
    return name

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def request_for(url):
    request = urllib.request.Request(url, headers={"User-Agent": "VideoDownloaderLocal/1.0", "Accept": "video/*, application/octet-stream, */*"})
    return urllib.request.build_opener(SafeRedirectHandler()).open(request, timeout=25)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send_json(self, code, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            body = (ROOT / "index.html").read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path in ("/style.css", "/app.js"):
            file = ROOT / path.lstrip("/"); body = file.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/css; charset=utf-8" if path.endswith("css") else "text/javascript; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/state":
            with lock: self.send_json(200, {"history": history(), "settings": settings(), "jobs": jobs}); return
        if path == "/api/choose-folder":
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
                chosen = filedialog.askdirectory(initialdir=settings().get("folder"), title="Escolha a pasta de destino"); root.destroy()
                if chosen: save_settings({"folder": chosen})
                self.send_json(200, {"folder": chosen or settings()["folder"]})
            except Exception as exc: self.send_json(500, {"error": f"Não foi possível abrir o seletor de pasta: {exc}"})
            return
        self.send_error(404)
    def do_POST(self):
        try: data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except (ValueError, json.JSONDecodeError): self.send_json(400, {"error": "Pedido inválido."}); return
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/inspect":
            try:
                url = safe_url(data.get("url", "")); advice = platform_advice(url)
                if advice: self.send_json(422, {"error": advice}); return
                with request_for(url) as response:
                    mime = response.headers.get_content_type()
                    if not (mime.startswith("video/") or mime in ("application/octet-stream", "binary/octet-stream")):
                        self.send_json(415, {"error": "O endereço não parece apontar diretamente para um arquivo de vídeo."}); return
                    length = int(response.headers.get("Content-Length", 0) or 0)
                    self.send_json(200, {"url": url, "title": filename_from(response, url), "mime": mime, "size": length, "sizeText": format_size(length) if length else "Tamanho não informado"})
            except urllib.error.HTTPError as exc: self.send_json(400, {"error": f"O servidor respondeu HTTP {exc.code}. O conteúdo pode ser privado, removido ou o link pode ter expirado."})
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc: self.send_json(400, {"error": str(exc) or "Falha de conexão. Verifique o link e tente novamente."})
            return
        if path == "/api/download":
            url = data.get("url", ""); jid = os.urandom(8).hex()
            try: safe_url(url)
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            with lock: jobs[jid] = {"id": jid, "status": "queued", "received": 0, "total": 0, "speed": 0, "url": url}
            threading.Thread(target=download, args=(jid, url), daemon=True).start(); self.send_json(202, {"id": jid}); return
        if path == "/api/cancel":
            jid = data.get("id")
            with lock:
                if jid in jobs: jobs[jid]["cancel"] = True
            self.send_json(200, {"ok": True}); return
        if path == "/api/history/remove":
            with lock:
                items = [x for x in history() if x.get("id") != data.get("id")]; save_history(items)
            self.send_json(200, {"ok": True}); return
        if path == "/api/history/clear":
            with lock: save_history([])
            self.send_json(200, {"ok": True}); return
        if path == "/api/settings":
            folder = Path(data.get("folder", "")).expanduser().resolve()
            try: folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc: self.send_json(400, {"error": f"Pasta inválida: {exc}"}); return
            if not folder.is_dir(): self.send_json(400, {"error": "O destino precisa ser uma pasta."}); return
            save_settings({"folder": str(folder)}); self.send_json(200, {"folder": str(folder)}); return
        if path == "/api/open-folder":
            folder = Path(settings()["folder"])
            try: os.startfile(folder); self.send_json(200, {"ok": True})
            except OSError as exc: self.send_json(500, {"error": str(exc)})
            return
        if path == "/api/open-file":
            target = Path(data.get("path", "")).expanduser().resolve()
            folder = Path(settings()["folder"]).resolve()
            try: target.relative_to(folder)
            except ValueError: self.send_json(400, {"error": "O arquivo não está na pasta de destino."}); return
            if not target.is_file(): self.send_json(404, {"error": "O arquivo não foi encontrado."}); return
            try: os.startfile(target); self.send_json(200, {"ok": True})
            except OSError as exc: self.send_json(500, {"error": str(exc)})
            return
        self.send_error(404)

def format_size(value):
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB": return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024

def download(jid, url):
    temp = None
    try:
        safe_url(url)
        with request_for(url) as response:
            mime = response.headers.get_content_type()
            if not (mime.startswith("video/") or mime in ("application/octet-stream", "binary/octet-stream")): raise ValueError("O servidor não entregou um arquivo de vídeo.")
            total = int(response.headers.get("Content-Length", 0) or 0); name = filename_from(response, url)
            folder = Path(settings()["folder"]); folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            stem, suffix = target.stem, target.suffix; n = 1
            while target.exists(): target = folder / f"{stem} ({n}){suffix}"; n += 1
            temp = target.with_name(target.name + ".part")
            started = datetime.now(timezone.utc).timestamp(); received = 0
            with temp.open("wb") as out:
                while True:
                    with lock:
                        if jobs[jid].get("cancel"): raise InterruptedError("Download cancelado.")
                        jobs[jid].update(status="downloading", total=total)
                    chunk = response.read(256 * 1024)
                    if not chunk: break
                    out.write(chunk); received += len(chunk); elapsed = max(0.1, datetime.now(timezone.utc).timestamp() - started)
                    with lock: jobs[jid].update(received=received, speed=received / elapsed)
            temp.replace(target); temp = None
        item = {"id": jid, "title": target.name, "path": str(target), "url": url, "size": received, "date": datetime.now().astimezone().isoformat()}
        with lock: save_history([item] + history()); jobs[jid].update(status="done", path=str(target), title=target.name, received=received, total=received)
    except InterruptedError as exc:
        if temp and temp.exists(): temp.unlink()
        with lock: jobs[jid].update(status="cancelled", error=str(exc))
    except Exception as exc:
        if temp and temp.exists(): temp.unlink()
        with lock: jobs[jid].update(status="error", error=str(exc) or "Falha durante o download.")

def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Video Downloader disponível em {url} (Ctrl+C para encerrar)", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(.8, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nAplicativo encerrado.")
    finally: server.server_close()

if __name__ == "__main__": main()
