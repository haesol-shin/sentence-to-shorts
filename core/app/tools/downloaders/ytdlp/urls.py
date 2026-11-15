"""Which links the downloader may open.

Only an exact HTTPS host of the three supported platforms passes. User info,
ports, IP literals, other schemes and look-alike hosts are refused before any
process starts. A failure names the rule that failed and never echoes the URL.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

from app.ports import AppError

ALLOWED_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "instagram.com",
        "www.instagram.com",
        "tiktok.com",
        "www.tiktok.com",
        "m.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    }
)
MAX_URL_CHARS = 500


def _refuse(reason: str) -> AppError:
    return AppError("url_not_allowed", detail={"reason": reason})


def check_url(url: str) -> str:
    """Return the URL without its fragment, or raise ``url_not_allowed``."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        raise _refuse("length")
    if not url.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise _refuse("characters")
    if "\\" in url:
        raise _refuse("characters")
    if url[:8].lower() != "https://":
        raise _refuse("scheme")
    try:
        parts = urlsplit(url)
    except ValueError as error:
        raise _refuse("syntax") from error
    netloc = parts.netloc
    if "@" in netloc:
        raise _refuse("userinfo")
    if netloc.startswith("["):
        raise _refuse("ip_literal")
    if ":" in netloc:
        raise _refuse("port")
    host = netloc.lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise _refuse("ip_literal")
    if host not in ALLOWED_HOSTS:
        raise _refuse("host")
    return urlunsplit(("https", host, parts.path, parts.query, ""))
