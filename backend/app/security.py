import ipaddress
import socket
from urllib.parse import urlsplit


PLATFORM_DOMAINS = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "instagram.com",
        "tiktok.com",
        "vm.tiktok.com",
        "facebook.com",
        "fb.watch",
        "x.com",
        "twitter.com",
        "t.co",
        "pinterest.com",
        "pin.it",
        "vimeo.com",
        "dailymotion.com",
        "twitch.tv",
        "reddit.com",
        "redd.it",
        "soundcloud.com",
        "streamable.com",
    }
)


class URLValidationError(ValueError):
    pass


def _is_allowed_host(host: str, extra_domains: frozenset[str]) -> bool:
    return any(
        host == domain or host.endswith("." + domain)
        for domain in PLATFORM_DOMAINS | extra_domains
    )


def validate_url(raw_url: str, extra_domains: frozenset[str] = frozenset()) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > 4096:
        raise URLValidationError("Informe um link válido.")
    try:
        parsed = urlsplit(raw_url.strip())
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError as exc:
        raise URLValidationError("O endereço informado não é válido.") from exc

    if parsed.scheme not in {"http", "https"} or not host:
        raise URLValidationError("Informe um link HTTP ou HTTPS de uma plataforma suportada.")
    if parsed.username or parsed.password:
        raise URLValidationError("Links com credenciais embutidas não são permitidos.")
    if port not in {None, 80, 443}:
        raise URLValidationError("Portas personalizadas não são permitidas.")
    if not _is_allowed_host(host, extra_domains):
        raise URLValidationError("Essa plataforma não está na lista de domínios permitidos.")

    try:
        addresses = {
            ipaddress.ip_address(result[4][0].split("%", 1)[0])
            for result in socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80))
        }
    except (OSError, ValueError) as exc:
        raise URLValidationError("Não foi possível localizar o servidor do link.") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise URLValidationError("Endereços locais ou de rede privada não são permitidos.")
    return parsed.geturl()


def validate_public_media_url(raw_url: str) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > 8192:
        raise URLValidationError("Endereço de prévia inválido.")
    try:
        parsed = urlsplit(raw_url.strip())
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError as exc:
        raise URLValidationError("Endereço de prévia inválido.") from exc

    if parsed.scheme not in {"http", "https"} or not host:
        raise URLValidationError("A prévia precisa usar HTTP ou HTTPS.")
    if parsed.username or parsed.password or port not in {None, 80, 443}:
        raise URLValidationError("Endereço de prévia não permitido.")

    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
        addresses = {address}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(result[4][0].split("%", 1)[0])
                for result in socket.getaddrinfo(
                    host, port or (443 if parsed.scheme == "https" else 80)
                )
            }
        except (OSError, ValueError) as exc:
            raise URLValidationError("Não foi possível localizar a prévia.") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise URLValidationError("Endereços locais ou de rede privada não são permitidos.")
    return parsed.geturl()
