import hashlib
import json
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


PYPI_JSON_URL = "https://pypi.org/pypi/yt-dlp/json"
MAX_WHEEL_SIZE = 50 * 1024 * 1024


def _require_https_host(url: str, host: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != host or parsed.port:
        raise ValueError(f"Origem inesperada ao consultar o pacote: {host}.")


def latest_release() -> dict[str, str]:
    request = Request(PYPI_JSON_URL, headers={"User-Agent": "SaveClip yt-dlp updater"})
    with urlopen(request, timeout=20) as response:
        _require_https_host(response.geturl(), "pypi.org")
        metadata = json.loads(response.read())

    release_version = metadata["info"]["version"]
    wheel = next(
        (
            item
            for item in metadata["urls"]
            if item.get("filename", "").endswith("-py3-none-any.whl")
        ),
        None,
    )
    if wheel is None:
        raise ValueError("A versão publicada não contém um wheel Python universal.")
    _require_https_host(wheel["url"], "files.pythonhosted.org")
    return {
        "version": release_version,
        "url": wheel["url"],
        "sha256": wheel["digests"]["sha256"],
    }


def download_verified_wheel(release: dict[str, str]) -> Path:
    _require_https_host(release["url"], "files.pythonhosted.org")
    request = Request(release["url"], headers={"User-Agent": "SaveClip yt-dlp updater"})
    with urlopen(request, timeout=30) as response:
        _require_https_host(response.geturl(), "files.pythonhosted.org")
        content = response.read(MAX_WHEEL_SIZE + 1)

    if len(content) > MAX_WHEEL_SIZE:
        raise ValueError("O wheel excede o limite de tamanho para atualização.")
    digest = hashlib.sha256(content).hexdigest()
    if digest.lower() != release["sha256"].lower():
        raise ValueError("O SHA-256 do wheel não confere com os metadados do PyPI.")

    with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as wheel_file:
        wheel_file.write(content)
        return Path(wheel_file.name)


def main() -> int:
    try:
        installed_version = version("yt-dlp")
        release = latest_release()
        print(f"Versão instalada: {installed_version}")
        print(f"Versão publicada no PyPI: {release['version']}")
        print(f"SHA-256 publicado: {release['sha256']}")
        if release["version"] == installed_version:
            print("O yt-dlp já está atualizado.")
            return 0
        confirmation = input(
            "Baixar o wheel oficial, verificar o SHA-256 e atualizar yt-dlp? [s/N] "
        )
        if confirmation.strip().lower() not in {"s", "sim"}:
            print("Atualização cancelada; nenhuma alteração foi feita.")
            return 0

        wheel_path = download_verified_wheel(release)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--no-index",
                    str(wheel_path),
                ],
                check=False,
            )
        finally:
            wheel_path.unlink(missing_ok=True)

        if result.returncode:
            print(f"A instalação falhou (código {result.returncode}).")
            return result.returncode
        updated_version = version("yt-dlp")
        if updated_version != release["version"]:
            print(
                "A versão instalada não corresponde à versão verificada; "
                "confira o ambiente Python."
            )
            return 1
        print(f"yt-dlp atualizado e verificado: {updated_version}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Não foi possível atualizar o yt-dlp: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
