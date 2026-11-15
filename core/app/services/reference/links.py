"""Which platform a pasted link belongs to.

The downloader owns the exact host allowlist and is the security boundary. This
module only names the platform for the stored summary and gives an early,
readable refusal before a job spends a download slot.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.ports import AppError
from app.schemas.video import ReferenceHost

PLATFORM_DOMAINS: dict[str, ReferenceHost] = {
    "youtube.com": ReferenceHost.youtube,
    "youtu.be": ReferenceHost.youtube,
    "instagram.com": ReferenceHost.instagram,
    "tiktok.com": ReferenceHost.tiktok,
}


def platform_of(url: str) -> ReferenceHost:
    """The platform of an https link, or ``url_not_allowed``. The URL is never kept."""
    try:
        parts = urlsplit(url)
    except ValueError as error:
        raise AppError("url_not_allowed", detail={"reason": "syntax"}) from error
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise AppError("url_not_allowed", detail={"reason": "scheme"})
    for domain, platform in PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return platform
    raise AppError("url_not_allowed", detail={"reason": "host"})
