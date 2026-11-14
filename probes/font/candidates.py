"""Font candidates and their pinned sources.

Every input is fetched at run time and checked against a SHA-256 pin, so the
probe never stores font files in the repository. The probe reads the license
file of each package and records its digest too.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

CHUNK = 1 << 20
TIMEOUT_SECONDS = 180.0
USER_AGENT = "font-caption-probe/1"
OFL_MARKER = "sil open font license"


class SourceError(RuntimeError):
    """An input could not be fetched, verified, or read."""


@dataclass(frozen=True)
class Artifact:
    """One downloadable file with its expected digest."""

    url: str
    sha256: str


@dataclass(frozen=True)
class Candidate:
    """A caption font with the package and license that carry it."""

    font_id: str
    family: str
    artifact: Artifact
    member: str | None
    license_artifact: Artifact
    license_member: str | None
    license_id: str


GALMURI_PACKAGE = Artifact(
    url="https://registry.npmjs.org/galmuri/-/galmuri-2.40.3.tgz",
    sha256="7d6b2b8534d157dd5e4eb8e01145f7388c0383bed8a96f5ec719eaacf1f86816",
)
GALMURI_LICENSE = Artifact(
    url=GALMURI_PACKAGE.url,
    sha256=GALMURI_PACKAGE.sha256,
)

CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        font_id="galmuri11",
        family="Galmuri11",
        artifact=GALMURI_PACKAGE,
        member="package/dist/Galmuri11.ttf",
        license_artifact=GALMURI_LICENSE,
        license_member="package/dist/LICENSE.txt",
        license_id="OFL-1.1",
    ),
    Candidate(
        font_id="galmuri14",
        family="Galmuri14",
        artifact=GALMURI_PACKAGE,
        member="package/dist/Galmuri14.ttf",
        license_artifact=GALMURI_LICENSE,
        license_member="package/dist/LICENSE.txt",
        license_id="OFL-1.1",
    ),
    Candidate(
        font_id="pretendard",
        family="Pretendard",
        artifact=Artifact(
            url="https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-Regular.otf",
            sha256="3ffbacde6ab8411f1d2db54bb9b1f0b3ee2a738932033722cf0388c06aed1c93",
        ),
        member=None,
        license_artifact=Artifact(
            url="https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/LICENSE.txt",
            sha256="b04538c9abec39a3db75108cf0af0fd9c77032fe8aa2cf38345b4d250e98e38e",
        ),
        license_member=None,
        license_id="OFL-1.1",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_sha256: str) -> str:
    """Return the measured digest, or fail when it differs from the pin."""
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise SourceError(f"{path.name}: SHA-256 {actual} does not match pin {expected_sha256}")
    return actual


def download(artifact: Artifact, dest: Path) -> str:
    """Fetch one artifact, checking its digest and its byte count."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(artifact.url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    written = 0
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        expected_bytes = response.headers.get("Content-Length")
        with dest.open("wb") as handle:
            while chunk := response.read(CHUNK):
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
    if expected_bytes is not None and int(expected_bytes) != written:
        dest.unlink(missing_ok=True)
        raise SourceError(f"{artifact.url}: read {written} of {expected_bytes} bytes")
    actual = digest.hexdigest()
    if actual != artifact.sha256:
        dest.unlink(missing_ok=True)
        raise SourceError(f"{artifact.url}: SHA-256 {actual} does not match pin {artifact.sha256}")
    return actual


def fetch(artifact: Artifact, downloads: Path) -> Path:
    """Return a cached download, verifying the pin on every run."""
    name = urlparse(artifact.url).path.rsplit("/", 1)[-1] or "download"
    path = downloads / name
    if path.is_file():
        try:
            verify_file(path, artifact.sha256)
            return path
        except SourceError:
            path.unlink()
    download(artifact, path)
    return path


def extract_member(archive: Path, member: str, dest: Path) -> str:
    """Copy one named file out of a tar archive and return its digest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tar:
        try:
            info = tar.getmember(member)
        except KeyError as error:
            raise SourceError(f"{archive.name}: no member {member}") from error
        if not info.isfile():
            raise SourceError(f"{archive.name}: member {member} is not a file")
        source = tar.extractfile(info)
        if source is None:
            raise SourceError(f"{archive.name}: member {member} cannot be read")
        with source, dest.open("wb") as handle:
            shutil.copyfileobj(source, handle)
    return sha256_file(dest)


def unpack(candidate: Candidate, downloads: Path, fonts_dir: Path) -> dict:
    """Fetch the package and license, then return the local paths and digests."""
    package = fetch(candidate.artifact, downloads)
    license_package = fetch(candidate.license_artifact, downloads)
    if candidate.member:
        font_name = candidate.member.rsplit("/", 1)[-1]
    else:
        font_name = urlparse(candidate.artifact.url).path.rsplit("/", 1)[-1]
    font_path = fonts_dir / font_name
    if candidate.member:
        font_sha256 = extract_member(package, candidate.member, font_path)
    else:
        font_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package, font_path)
        font_sha256 = sha256_file(font_path)
    license_path = fonts_dir / f"{candidate.font_id}.license.txt"
    if candidate.license_member:
        license_sha256 = extract_member(license_package, candidate.license_member, license_path)
    else:
        license_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(license_package, license_path)
        license_sha256 = sha256_file(license_path)
    text = license_path.read_text(encoding="utf-8", errors="replace")
    notice = next((line.strip() for line in text.splitlines() if "Copyright" in line), "")
    return {
        "package": {"url": candidate.artifact.url, "sha256": candidate.artifact.sha256},
        "font_path": font_path,
        "font_sha256": font_sha256,
        "license": {
            "url": candidate.license_artifact.url,
            "sha256": license_sha256,
            "declared": candidate.license_id,
            "notice": notice,
            "ofl_text_found": OFL_MARKER in text.lower(),
        },
    }
