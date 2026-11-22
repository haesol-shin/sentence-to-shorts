"""The FFmpeg source manifest and the source staging API."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
PACKAGING = REPO / "packaging"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "packaging_corresponding_source", PACKAGING / "corresponding_source.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["packaging_corresponding_source"] = module
    spec.loader.exec_module(module)
    return module


module = load_module()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_blobs() -> dict[str, bytes]:
    blobs = {}
    for name in ("ffmpeg", "x264", "x265", "builder"):
        data = f"{name} source".encode()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo(f"{name}/README")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        blobs[f"https://download.invalid/{name}.tar.gz"] = gzip.compress(
            stream.getvalue(), mtime=0
        )
    return blobs


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def serve(monkeypatch: pytest.MonkeyPatch, blobs: dict[str, bytes]) -> None:
    def open_url(request: object, timeout: int) -> Response:
        return Response(blobs[request.full_url])  # type: ignore[attr-defined]

    monkeypatch.setattr(module.urllib.request, "urlopen", open_url)


def manifest(tmp_path: Path, *, bad_source: str | None = None) -> Path:
    blobs = source_blobs()
    artifacts = {}
    for name, label in (
        ("ffmpeg", "ffmpeg.tar.gz"),
        ("x264", "x264.tar.gz"),
        ("x265", "x265.tar.gz"),
        ("builder", "builder.tar.gz"),
    ):
        url = f"https://download.invalid/{label}"
        blob = b"broken" if bad_source == name else blobs[url]
        artifacts[name] = {
            "url": url,
            "bytes": len(blob),
            "sha256": digest(blob),
            "filename": f"{name}-{label}",
            "component": name,
            "revision": "0" * 40,
        }
    data = {
        "schema_version": 1,
        "builds": {
            "linux-x86_64": {
                "revision": "1" * 40,
                "binary": {"file": "ffmpeg-linux", "bytes": 4, "sha256": digest(b"exe!")},
                "builder": {"name": "Example Builder", "release": "test-1", "revision": "2" * 40},
                "configure": ["--enable-gpl", "--enable-libx264"],
                "sources": ["ffmpeg", "x264", "builder"],
                "instructions": ["Run the builder scripts."],
            },
            "windows-x86_64": {
                "revision": "1" * 40,
                "binary": {"file": "ffmpeg.exe", "bytes": 4, "sha256": digest(b"exe!")},
                "builder": {"name": "Example Builder", "release": "test-1", "revision": "2" * 40},
                "configure": ["--enable-gpl", "--enable-libx265"],
                "sources": ["ffmpeg", "x265", "builder"],
                "instructions": ["Run the builder scripts."],
            },
        },
        "artifacts": artifacts,
    }
    path = tmp_path / "ffmpeg-sources.lock.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_corresponding_source_manifest_maps_every_shipped_binary_to_verified_sources() -> None:
    shipped = json.loads((PACKAGING / "ffmpeg.lock.json").read_text(encoding="utf-8"))
    sources = module.load_manifest()
    assert set(sources["builds"]) == set(shipped["builds"])
    for label, build in sources["builds"].items():
        binary = build["binary"]
        pinned = shipped["builds"][label]
        assert binary["file"] == Path(str(pinned["member"])).name
        assert binary["member"] == pinned["member"]
        assert binary["bytes"] == pinned["bytes"]
        assert binary["sha256"] == pinned["sha256"]
        assert "ffmpeg" in build["sources"] and "btbn-build" in build["sources"]
        assert not build.get("unresolved")
        for name in build["sources"]:
            artifact = sources["artifacts"][name]
            assert artifact["bytes"] > 0
            assert len(artifact["sha256"]) == 64
            assert artifact["sha256"].isalnum() or all(
                character in "0123456789abcdef" for character in artifact["sha256"]
            )
            if artifact.get("files") is None:
                if artifact.get("crate") is None:
                    assert artifact["url"].startswith("https://")
                else:
                    assert module._artifact_url(artifact).startswith("https://")
            else:
                assert artifact["base_url"].startswith("https://")
    ffmpeg = sources["artifacts"]["ffmpeg"]
    assert ffmpeg["revision"] == shipped["revision"]
    builder = sources["artifacts"]["btbn-build"]
    assert builder["revision"] == "6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b"


def test_corresponding_source_stages_the_selected_platform_and_writes_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = manifest(tmp_path)
    monkeypatch.setattr(module, "MANIFEST", path)
    blobs = source_blobs()
    serve(monkeypatch, blobs)
    target = tmp_path / "asset"
    module.stage_sources("linux-x86_64", target, tmp_path / "work")
    names = sorted(item.name for item in target.iterdir())
    assert names == [
        "SOURCE-README",
        "builder-builder.tar.gz",
        "ffmpeg-ffmpeg.tar.gz",
        "ffmpeg-sources.lock.json",
        "x264-x264.tar.gz",
    ]
    with tarfile.open(target / "ffmpeg-ffmpeg.tar.gz") as archive:
        handle = archive.extractfile("ffmpeg/README")
        assert handle is not None
        with handle:
            assert handle.read() == b"ffmpeg source"
    assert (target / "ffmpeg-sources.lock.json").read_bytes() == path.read_bytes()
    text = (target / "SOURCE-README").read_text(encoding="utf-8")
    assert "ffmpeg-linux" in text
    assert "Example Builder" in text
    assert "test-1" in text
    assert "--enable-libx264" in text
    assert "x265" not in text
    in_code = False
    headings = []
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("## "):
            headings.append(line)
    assert not in_code
    assert "## Source archives" in headings
    assert "## Rebuilding" in headings
    assert (tmp_path / "work" / "ffmpeg-sources" / "ffmpeg-ffmpeg.tar.gz").is_file()


def test_corresponding_source_reuses_a_verified_work_file_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = manifest(tmp_path)
    monkeypatch.setattr(module, "MANIFEST", path)
    work = tmp_path / "work" / "ffmpeg-sources"
    work.mkdir(parents=True)
    blobs = source_blobs()
    for source, blob in blobs.items():
        name = source.rsplit("/", 1)[1].replace(".tar.gz", "")
        (work / f"{name}-{name}.tar.gz").write_bytes(blob)
    calls: list[str] = []

    def fail(request: object, timeout: int) -> Response:
        calls.append(str(request))
        raise AssertionError("network must not be used")

    monkeypatch.setattr(module.urllib.request, "urlopen", fail)
    target = tmp_path / "asset"
    module.stage_sources("linux-x86_64", target, tmp_path / "work")
    assert calls == []
    assert len(list(target.glob("*.tar.gz"))) == 3


def test_corresponding_source_refuses_a_bad_hash_and_leaves_no_bundle_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = manifest(tmp_path, bad_source="x264")
    monkeypatch.setattr(module, "MANIFEST", path)
    blobs = source_blobs()
    serve(monkeypatch, blobs)
    target = tmp_path / "asset"
    with pytest.raises(module.SourceError, match="does not match"):
        module.stage_sources("linux-x86_64", target, tmp_path / "work")
    assert not target.exists()
    assert not list((tmp_path / "work").rglob("*.part"))


def test_corresponding_source_rejects_a_missing_source_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = manifest(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["builds"]["linux-x86_64"]["sources"].append("missing")
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(module, "MANIFEST", path)
    with pytest.raises(module.SourceError, match="unknown source archive"):
        module.load_manifest()
    with pytest.raises(module.SourceError, match="unknown source archive"):
        module.stage_sources("linux-x86_64", tmp_path / "bundle", tmp_path / "work")


def test_corresponding_source_rejects_an_unknown_platform_and_unresolved_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = manifest(tmp_path)
    monkeypatch.setattr(module, "MANIFEST", path)
    with pytest.raises(module.SourceError, match="no build"):
        module.stage_sources("windows-aarch64", tmp_path / "asset", tmp_path / "work")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["builds"]["linux-aarch64"] = {
        **data["builds"]["linux-x86_64"],
        "unresolved": ["private build scripts"],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(module.SourceError, match="unresolved source"):
        module.load_manifest()
    with pytest.raises(module.SourceError, match="invalid platform label"):
        module.asset_name("../escape")


def test_corresponding_source_notice_lines_name_the_release_asset_and_have_no_em_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = manifest(tmp_path)
    monkeypatch.setattr(module, "MANIFEST", path)
    text = "\n".join(module.notice_lines())
    assert module.asset_name("linux-x86_64") == "ffmpeg-corresponding-source-linux-x86_64.tar"
    assert "ffmpeg-corresponding-source-linux-x86_64.tar" in text
    assert "ffmpeg-corresponding-source-windows-x86_64.tar" in text
    assert "three years" in text
    assert "SOURCE-README" in text
    assert "linux-x86_64" in text and "windows-x86_64" in text
    assert "Example Builder" in text
    assert "\u2014" not in text


def test_corresponding_source_stages_a_hash_pinned_file_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = "https://source.invalid/revision/"
    first = b"first source file"
    second = b"second source file"
    files = {
        "README": {"bytes": len(first), "sha256": digest(first)},
        "src/second.c": {"bytes": len(second), "sha256": digest(second)},
    }
    data = {
        "schema_version": 1,
        "builds": {
            "linux-x86_64": {
                "revision": "1" * 40,
                "binary": {"file": "ffmpeg-linux", "bytes": 4, "sha256": digest(b"exe!")},
                "sources": ["export"],
            }
        },
        "artifacts": {
            "export": {
                "base_url": base,
                "files": files,
                "bytes": len(first) + len(second),
                "sha256": module._tree_digest(files),
                "filename": "export",
                "component": "exported component",
                "revision": "r42",
            }
        },
    }
    path = tmp_path / "ffmpeg-sources.lock.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(module, "MANIFEST", path)
    blobs = {base + "README": first, base + "src/second.c": second}
    serve(monkeypatch, blobs)
    target = tmp_path / "asset"
    module.stage_sources("linux-x86_64", target, tmp_path / "work")
    assert (target / "export" / "README").read_bytes() == first
    assert (target / "export" / "src" / "second.c").read_bytes() == second
    readme = (target / "SOURCE-README").read_text(encoding="utf-8")
    assert "| `export/` |" in readme
    assert "tree digest" in readme
    assert (target / "ffmpeg-sources.lock.json").is_file()


def test_corresponding_source_pins_librist_as_a_file_export_at_its_revision() -> None:
    """GitLab refuses the generated librist archive, so its files are pinned one by one."""
    data = module.load_manifest()
    artifact = data["artifacts"]["50-librist"]
    assert "url" not in artifact
    assert artifact["base_url"].endswith(f"/-/raw/{artifact['revision']}/")
    files = artifact["files"]
    assert files
    assert artifact["sha256"] == module._tree_digest(files)
    assert artifact["bytes"] == sum(meta["bytes"] for meta in files.values())
    assert {"meson.build", "COPYING"} <= set(files)


def test_corresponding_source_rejects_a_bad_file_export_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = manifest(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    files = {"a.txt": {"bytes": 1, "sha256": digest(b"a")}}
    data["artifacts"]["export"] = {
        "base_url": "https://source.invalid/revision/",
        "files": files,
        "bytes": 2,
        "sha256": module._tree_digest(files),
        "filename": "export",
        "component": "exported component",
        "revision": "r42",
    }
    data["builds"]["linux-x86_64"]["sources"] = ["export"]
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(module, "MANIFEST", path)
    with pytest.raises(module.SourceError, match="byte count"):
        module.load_manifest()


def test_corresponding_source_download_keeps_no_partial_file_on_short_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "archive.tar.gz"
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda request, timeout: Response(b"short")
    )
    with pytest.raises(module.SourceError):
        module.download_artifact(
            "https://download.invalid/short", target, {"bytes": 10, "sha256": "0" * 64}
        )
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


@pytest.mark.parametrize("cached", [False, True])
def test_corresponding_source_rejects_a_pinned_login_page_as_a_source_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cached: bool,
) -> None:
    path = manifest(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    artifact = data["artifacts"]["ffmpeg"]
    page = b"<html><title>Sign in</title><body>Authentication required</body></html>"
    artifact["bytes"], artifact["sha256"] = len(page), digest(page)
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(module, "MANIFEST", path)
    blobs = source_blobs()
    blobs[artifact["url"]] = page
    serve(monkeypatch, blobs)
    work = tmp_path / "work"
    if cached:
        cache = work / "ffmpeg-sources" / artifact["filename"]
        cache.parent.mkdir(parents=True)
        cache.write_bytes(page)
    target = tmp_path / "asset"
    with pytest.raises(module.SourceError, match="not a gzip archive"):
        module.stage_sources("linux-x86_64", target, work)
    assert not target.exists()
    assert not list(work.rglob("*.part"))


def tree_archive(files: dict[str, bytes], *, mtime: int, level: int) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mtime = mtime
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
    return gzip.compress(stream.getvalue(), compresslevel=level, mtime=mtime)


def tree_manifest(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, str]:
    """A manifest whose only source is a tree-pinned gitiles archive."""
    reference = tmp_path / "reference.tar.gz"
    reference.write_bytes(tree_archive(files, mtime=1, level=1))
    tree, total = module._tree_content(reference, reference.name)
    url = "https://source.invalid/project/+archive/" + "a" * 40 + ".tar.gz"
    data = {
        "schema_version": 1,
        "builds": {
            "linux-x86_64": {
                "revision": "1" * 40,
                "binary": {"file": "ffmpeg-linux", "bytes": 4, "sha256": digest(b"exe!")},
                "sources": ["project"],
            }
        },
        "artifacts": {
            "project": {
                "url": url,
                "verify": "tree",
                "bytes": total,
                "sha256": tree,
                "filename": "project.tar.gz",
                "component": "project",
                "revision": "a" * 40,
            }
        },
    }
    path = tmp_path / "ffmpeg-sources.lock.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, url


def test_corresponding_source_accepts_two_archives_of_one_tree_with_different_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"README": b"one", "src/main.c": b"int main(void);"}
    path, url = tree_manifest(tmp_path, files)
    monkeypatch.setattr(module, "MANIFEST", path)
    first = tree_archive(files, mtime=100, level=9)
    second = tree_archive(files, mtime=200, level=6)
    assert first != second
    for index, blob in enumerate((first, second)):
        serve(monkeypatch, {url: blob})
        target = tmp_path / f"asset{index}"
        module.stage_sources("linux-x86_64", target, tmp_path / f"work{index}")
        assert (target / "project.tar.gz").read_bytes() == blob


def test_corresponding_source_rejects_a_changed_file_in_a_tree_pinned_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"README": b"one", "src/main.c": b"int main(void);"}
    path, url = tree_manifest(tmp_path, files)
    monkeypatch.setattr(module, "MANIFEST", path)
    serve(monkeypatch, {url: tree_archive({**files, "README": b"two"}, mtime=1, level=6)})
    with pytest.raises(module.SourceError, match="pinned tree SHA-256"):
        module.stage_sources("linux-x86_64", tmp_path / "asset", tmp_path / "work")
    assert not (tmp_path / "asset").exists()


def test_corresponding_source_rejects_a_login_page_for_a_tree_pinned_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, url = tree_manifest(tmp_path, {"README": b"one"})
    monkeypatch.setattr(module, "MANIFEST", path)
    serve(monkeypatch, {url: b"<html><title>Sign in</title></html>"})
    with pytest.raises(module.SourceError, match="not a gzip archive"):
        module.stage_sources("linux-x86_64", tmp_path / "asset", tmp_path / "work")


def test_corresponding_source_requires_a_tree_pin_for_every_gitiles_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = tree_manifest(tmp_path, {"README": b"one"})
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["artifacts"]["project"]["verify"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(module.SourceError, match="gitiles archive"):
        module.load_manifest(path)
