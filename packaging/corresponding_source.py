"""Complete corresponding source for the FFmpeg executables in a distribution.

The manifest beside this module pins, for every shipped platform, the executable
that the runtime installs and the source archives and build materials that produced
it.  ``stage_sources`` downloads every source, checks its byte count and SHA-256
(for a gitiles ``+archive``, which is rebuilt per request, the digest of the extracted
tree; for a file export, every file's own SHA-256 and the digest of the file list),
and writes the verified files plus the manifest and ``SOURCE-README`` into one
directory that the caller packs as a Release asset.  The README explains how the
sources map to the executable and how to rebuild it.  ``notice_lines`` returns the
matching Markdown section for the distribution notices, and ``asset_name`` gives
the Release asset name for a platform.

Only the standard library is used, so this module runs before any dependency is
installed.  Archives are never committed to the repository: the build downloads
them from the pinned upstream locations.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "ffmpeg-sources.lock.json"
README_NAME = "SOURCE-README"
CHUNK = 1 << 20
SHA256 = re.compile(r"[0-9a-f]{64}")
LABEL = re.compile(r"[a-z0-9]+-[a-z0-9_]+")
CRATE = re.compile(r"[a-z0-9_-]+")
CRATES = "https://static.crates.io/crates"


def _artifact_url(artifact: Mapping[str, Any]) -> str:
    """The archive URL of one source artifact.

    A crates.io archive may name its crate and revision instead of spelling out the
    registry path, so the registry layout lives in one place.
    """
    crate = artifact.get("crate")
    if crate is None:
        return str(artifact["url"])
    revision = str(artifact["revision"])
    return f"{CRATES}/{crate}/{crate}-{revision}.crate"


class SourceError(RuntimeError):
    """The corresponding source cannot be staged as the manifest promises."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(files: Mapping[str, Mapping[str, Any]]) -> str:
    text = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_relative(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path:
        return False
    parts = path.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _checked_file_export(
    artifact: Mapping[str, Any], where: str, size: int, digest: str
) -> None:
    files = artifact.get("files")
    if not isinstance(files, dict) or not files:
        raise SourceError(f"{where} has an empty file export")
    base = artifact.get("base_url")
    if not isinstance(base, str) or not base.startswith("https://") or not base.endswith("/"):
        raise SourceError(f"{where} has no HTTPS base URL")
    total = 0
    for path, meta in files.items():
        if not isinstance(path, str) or not _safe_relative(path):
            raise SourceError(f"{where} has an unsafe exported path")
        if not isinstance(meta, dict):
            raise SourceError(f"{where} has no metadata for a file")
        count = meta.get("bytes")
        if not isinstance(count, int) or count < 0:
            raise SourceError(f"{where} has no byte count for a file")
        file_digest = meta.get("sha256")
        if not isinstance(file_digest, str) or SHA256.fullmatch(file_digest) is None:
            raise SourceError(f"{where} has no SHA-256 for a file")
        total += count
    if total != size:
        raise SourceError(f"{where} byte count does not match its file export")
    if _tree_digest(files) != digest:
        raise SourceError(f"{where} tree digest does not match its file export")


def _checked_artifact(artifact: Mapping[str, Any], where: str) -> None:
    name = artifact.get("filename")
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise SourceError(f"{where} has an unsafe archive file name")
    component = artifact.get("component")
    if not isinstance(component, str) or not component:
        raise SourceError(f"{where} has no component name")
    revision = artifact.get("revision")
    if not isinstance(revision, str) or not revision:
        raise SourceError(f"{where} has no source revision")
    size = artifact.get("bytes")
    if not isinstance(size, int) or size < 0:
        raise SourceError(f"{where} has no byte count")
    digest = artifact.get("sha256")
    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
        raise SourceError(f"{where} has no SHA-256")
    if artifact.get("files") is not None:
        _checked_file_export(artifact, where, size, digest)
        return
    if artifact.get("crate") is not None:
        crate = artifact["crate"]
        if not isinstance(crate, str) or CRATE.fullmatch(crate) is None:
            raise SourceError(f"{where} has an unsafe crate name")
    else:
        url = artifact.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise SourceError(f"{where} has no HTTPS source URL")
    if size <= 0:
        raise SourceError(f"{where} has no positive byte count")
    verify = artifact.get("verify")
    if verify not in (None, "tree"):
        raise SourceError(f"{where} has an unknown verification mode")
    url = artifact.get("url")
    if isinstance(url, str) and "/+archive/" in url:
        # Gitiles builds these archives per request, so their bytes are not stable.
        if verify != "tree":
            raise SourceError(f"{where} is a gitiles archive and must pin its tree digest")
        if revision not in url:
            raise SourceError(f"{where} URL does not name its revision")


def _checked_build(label: str, build: Mapping[str, Any], artifacts: Mapping[str, Any]) -> None:
    binary = build.get("binary")
    if not isinstance(binary, dict):
        raise SourceError(f"build {label} has no binary")
    if not isinstance(binary.get("file"), str) or not binary["file"]:
        raise SourceError(f"build {label} has no executable name")
    if not isinstance(binary.get("bytes"), int) or binary["bytes"] <= 0:
        raise SourceError(f"build {label} has no executable byte count")
    binary_digest = binary.get("sha256")
    if not isinstance(binary_digest, str) or SHA256.fullmatch(binary_digest) is None:
        raise SourceError(f"build {label} has no executable SHA-256")
    unresolved = build.get("unresolved", [])
    if unresolved:
        joined = ", ".join(map(str, unresolved))
        raise SourceError(f"build {label} has unresolved source: {joined}")
    names = build.get("sources")
    if not isinstance(names, list) or not names:
        raise SourceError(f"build {label} names no source archives")
    if len(set(names)) != len(names):
        raise SourceError(f"build {label} names a source archive twice")
    for name in names:
        if name not in artifacts:
            raise SourceError(f"build {label} names unknown source archive {name}")


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """Read and structurally check the source manifest.

    Every build must name its executable and at least one source artifact; every
    named artifact must exist in the shared artifact table.  A manifest that says
    a build is unresolved is rejected instead of silently staging less.
    """
    source = path if path is not None else MANIFEST
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SourceError(f"missing source manifest {source.name}") from error
    except (OSError, ValueError) as error:
        raise SourceError(f"cannot read source manifest {source.name}: {error}") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SourceError("source manifest has an unsupported schema")
    artifacts = data.get("artifacts")
    builds = data.get("builds")
    if not isinstance(artifacts, dict) or not isinstance(builds, dict) or not builds:
        raise SourceError("source manifest has no builds or artifacts")
    for artifact_id, artifact in artifacts.items():
        if not isinstance(artifact_id, str) or not artifact_id:
            raise SourceError("source manifest has an empty artifact id")
        if not isinstance(artifact, dict):
            raise SourceError(f"source artifact {artifact_id} is not an object")
        _checked_artifact(artifact, f"source artifact {artifact_id}")
    for label, build in builds.items():
        if not isinstance(label, str) or LABEL.fullmatch(label) is None:
            raise SourceError("source manifest has an invalid platform label")
        if not isinstance(build, dict):
            raise SourceError(f"build {label} is not an object")
        _checked_build(label, build, artifacts)
    return data


def _check_archive(path: Path, name: str) -> None:
    """Do not authenticate a login page as a source archive, even if its hash was pinned."""
    if name.endswith((".tar.gz", ".tgz")):
        with path.open("rb") as stream:
            if stream.read(3) != b"\x1f\x8b\x08":
                raise SourceError(f"{name} is not a gzip archive")


def _tree_content(path: Path, name: str) -> tuple[str, int]:
    """The tree digest and total file bytes of a tar.gz, independent of how it is packed.

    The digest covers sorted member paths, modes and file bytes (link targets for
    symlinks), not timestamps, ownership or compression, so two downloads of the
    same revision agree even when the server builds the archive on every request.
    """
    entries: dict[str, dict[str, Any]] = {}
    total = 0
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                relative = member.name[2:] if member.name.startswith("./") else member.name
                relative = relative.rstrip("/")
                if member.isdir():
                    continue
                if not _safe_relative(relative):
                    raise SourceError(f"{name} has an unsafe member path")
                if member.issym():
                    entries[relative] = {"mode": "120000", "link": member.linkname}
                elif member.isreg():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise SourceError(f"{name} has an unreadable member")
                    digest = hashlib.sha256()
                    with stream:
                        for block in iter(lambda: stream.read(CHUNK), b""):
                            digest.update(block)
                    entries[relative] = {
                        "mode": format(member.mode & 0o777, "o"),
                        "bytes": member.size,
                        "sha256": digest.hexdigest(),
                    }
                    total += member.size
                else:
                    raise SourceError(f"{name} has a member that is not a file or a link")
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise SourceError(f"cannot read {name} as a source archive: {error}") from error
    return _tree_digest(entries), total


def _check_archive_content(path: Path, name: str, artifact: Mapping[str, Any]) -> None:
    """Refuse an archive unless its bytes (or, for a tree-pinned one, its content) match."""
    if artifact.get("verify") == "tree":
        _check_archive(path, name)
        digest, total = _tree_content(path, name)
        if digest != artifact["sha256"] or total != artifact["bytes"]:
            raise SourceError(f"{name} does not match its pinned tree SHA-256")
        return
    if path.stat().st_size != artifact["bytes"] or _sha256_file(path) != artifact["sha256"]:
        raise SourceError(f"{name} does not match its pinned bytes and SHA-256")
    _check_archive(path, name)


def _archive_matches(path: Path, artifact: Mapping[str, Any]) -> bool:
    if not path.is_file():
        return False
    try:
        _check_archive_content(path, path.name, artifact)
    except SourceError:
        return False
    return True


def download_artifact(url: str, target: Path, artifact: Mapping[str, Any]) -> None:
    """Download one archive and refuse it unless it matches its pin.

    The pin is the byte count and SHA-256, or for ``"verify": "tree"`` the digest of
    the extracted tree.  The temporary file is removed on any mismatch, so a failed
    attempt cannot be mistaken for a verified archive on the next run.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "corresponding-source"})
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    try:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=900) as response:  # noqa: S310
                    with temporary.open("wb") as out:
                        shutil.copyfileobj(response, out, CHUNK)
                break
            except urllib.error.HTTPError as error:
                if error.code < 500 and error.code not in {408, 429}:
                    raise SourceError(f"cannot download {target.name}: {error}") from error
                if attempt == 2:
                    raise SourceError(f"cannot download {target.name}: {error}") from error
                time.sleep(1 + attempt)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt == 2:
                    raise SourceError(f"cannot download {target.name}: {error}") from error
                time.sleep(1 + attempt)
        _check_archive_content(temporary, target.name, artifact)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_paths(
    manifest: Mapping[str, Any], label: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    builds = manifest["builds"]
    build = builds.get(label)
    if build is None:
        raise SourceError(f"the source manifest has no build for {label}")
    artifacts = manifest["artifacts"]
    selected = [artifacts[name] for name in build["sources"]]
    names = [str(artifact["filename"]) for artifact in selected]
    if len(set(names)) != len(names):
        raise SourceError(f"build {label} has two source archives with the same file name")
    return build, selected


def _stage_instructions(
    build: Mapping[str, Any], selected: list[dict[str, Any]], label: str
) -> str:
    binary = build["binary"]
    builder = build.get("builder") or {}
    lines = [
        "# FFmpeg corresponding source",
        "",
        "This folder contains the source code and build materials for the FFmpeg "
        "executable shipped in one distribution archive. The executable was not built "
        "by this project; it was taken from the release named below and checked against "
        "the recorded SHA-256 when the distribution was built. The folder is published "
        f"as the `{asset_name(label)}` Release asset and is retained for at least three "
        "years after publication.",
        "",
        "## Shipped executable",
        "",
        f"- File: `{binary['file']}`",
        f"- Bytes: {binary['bytes']}",
        f"- SHA-256: `{binary['sha256']}`",
        f"- FFmpeg revision: `{build.get('revision', '')}`",
    ]
    if builder:
        lines += [
            f"- Builder: {builder.get('name', '')}",
            f"- Builder release: `{builder.get('release', '')}`",
            f"- Builder scripts revision: `{builder.get('revision', '')}`",
        ]
    lines += ["", "## Build configuration", "", "```"]
    lines += [f"'{flag}'," for flag in build.get("configure", [])]
    lines += ["```", "", "## Source archives", ""]
    lines += [
        "| File | Component | Revision | Bytes | SHA-256 | Upstream |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for artifact in selected:
        name = artifact["filename"]
        if artifact.get("files") is not None:
            name = name + "/"
        upstream = artifact.get("base_url") or _artifact_url(artifact)
        lines.append(
            f"| `{name}` | {artifact['component']} | `{artifact['revision']}` "
            f"| {artifact['bytes']} | `{artifact['sha256']}` | {upstream} |"
        )
    if any(artifact.get("files") is not None for artifact in selected):
        lines += [
            "",
            "An entry whose file name ends with `/` is a folder of files fetched one by "
            "one at a pinned revision, not a tarball. Its SHA-256 column is a tree digest: "
            "the SHA-256 of the sorted list of every file's path, byte count and SHA-256, "
            "and each listed file was checked against its own SHA-256 and byte count.",
        ]
    lines += ["", "## Rebuilding", ""]
    lines += list(build.get("instructions", []))
    lines += [
        "",
        "The build materials archive contains the complete configure invocation, the "
        "patches and the scripts that download and build every component. The source "
        "archives in this folder are the revisions those scripts selected. Where a "
        "component's build fetches subprojects, Rust crates or other generated inputs, "
        "the builder scripts name the exact mechanism and the revisions they use.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _stage_file_export(artifact: Mapping[str, Any], root: Path) -> None:
    """Fetch one versioned file export and verify every file before it is reused."""
    files = artifact["files"]
    base = str(artifact["base_url"])
    for path, meta in sorted(files.items()):
        target = root.joinpath(*path.split("/"))
        count = int(meta["bytes"])
        digest = str(meta["sha256"])
        if target.is_file() and target.stat().st_size == count and _sha256_file(target) == digest:
            continue
        target.unlink(missing_ok=True)
        download_artifact(base + path, target, {"bytes": count, "sha256": digest})


def _copy_verified(source: Path, target: Path, count: int, digest: str) -> None:
    if target.is_file() and target.stat().st_size == count and _sha256_file(target) == digest:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    shutil.copy(source, temporary)
    temporary.replace(target)


def stage_sources(label: str, dest: Path, work: Path) -> None:
    """Download, verify and write the complete source set for one platform.

    ``dest`` is the root of a source archive, not a bundle.  It receives every
    verified source artifact, a copy of the manifest and ``SOURCE-README``.  The
    caller packs that directory as ``ffmpeg-corresponding-source-<label>.tar`` and
    attaches it to the same release as the distribution.  ``work`` holds downloads
    between runs.  No file is written to ``dest`` until every artifact for the build
    has passed its pinned byte count and SHA-256 check.
    """
    manifest = load_manifest()
    build, selected = _artifact_paths(manifest, label)
    downloads = Path(work) / "ffmpeg-sources"
    verified: list[tuple[dict[str, Any], Path]] = []
    for artifact in selected:
        path = downloads / str(artifact["filename"])
        files = artifact.get("files")
        if files is not None:
            _stage_file_export(artifact, path)
            verified.append((artifact, path))
            continue
        if _archive_matches(path, artifact):
            verified.append((artifact, path))
            continue
        path.unlink(missing_ok=True)
        download_artifact(_artifact_url(artifact), path, artifact)
        verified.append((artifact, path))
    output = Path(dest)
    output.mkdir(parents=True, exist_ok=True)
    for artifact, path in verified:
        destination = output / str(artifact["filename"])
        files = artifact.get("files")
        if files is not None:
            for name, meta in sorted(files.items()):
                _copy_verified(
                    path.joinpath(*name.split("/")),
                    destination.joinpath(*name.split("/")),
                    int(meta["bytes"]),
                    str(meta["sha256"]),
                )
            continue
        if _archive_matches(destination, artifact):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        shutil.copy(path, temporary)
        temporary.replace(destination)
    shutil.copyfile(MANIFEST, output / MANIFEST.name)
    (output / README_NAME).write_text(_stage_instructions(build, selected, label), encoding="utf-8")


def asset_name(label: str) -> str:
    """The Release asset that carries the corresponding source for one platform."""
    if LABEL.fullmatch(label) is None:
        raise SourceError(f"invalid platform label {label}")
    return f"ffmpeg-corresponding-source-{label}.tar"


def notice_lines() -> list[str]:
    """Markdown lines that point readers at the same Release's source asset."""
    manifest = load_manifest()
    builds = manifest["builds"]
    lines = [
        "",
        "## FFmpeg corresponding source",
        "",
        "Distributions carry an FFmpeg executable taken from a pinned upstream build. "
        "It is built with `--enable-gpl --enable-version3`, so it is licensed "
        "GPL-3.0-or-later. The license text is in the `licenses` folder.",
        "",
        "The complete corresponding source for every shipped executable is attached to "
        "the same Release as the distribution, as an asset named "
        "`ffmpeg-corresponding-source-<platform>.tar`. The asset contains the exact "
        "FFmpeg revision, the source archives for the external libraries enabled in the "
        "build, the builder release's scripts, patches and configuration, a copy of "
        "`ffmpeg-sources.lock.json`, and `SOURCE-README`. That README maps the "
        "executable to the archives and explains how to rebuild it. Every archive is "
        "checked against its pinned byte count and SHA-256 when the asset is made. The "
        "Release assets stay available for at least three years after publication.",
        "",
        "| Platform | Release asset | FFmpeg revision | Builder |",
        "| --- | --- | --- | --- |",
    ]
    for label in sorted(builds):
        build = builds[label]
        builder = build.get("builder") or {}
        lines.append(
            f"| {label} | `{asset_name(label)}` | `{build.get('revision', '')}` "
            f"| {builder.get('name', '')} `{builder.get('release', '')}` |"
        )
    lines.append("")
    return lines
