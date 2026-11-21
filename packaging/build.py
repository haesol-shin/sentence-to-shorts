#!/usr/bin/env python3
"""Build the distribution: a bundle folder, then a Linux tarball or a Windows installer.

    python packaging/build.py bundle  --os linux --profile release --out dist \\
        --web frontend/dist --poetry "poetry"
    python packaging/build.py archive --os linux --bundle dist/<bundle> --out dist
    python packaging/build.py notices [--check]
    python packaging/build.py sources --os linux --out dist
    python packaging/build.py sums dist/<file> ... --out dist/SHA256SUMS

Names come from `core/config/brand.yaml`. Python is the pinned python-build-standalone
archive (`python.lock.json`), checked against its SHA-256 before it is unpacked. The
Python packages come from `poetry export` with hashes and are installed with
`uv pip sync --require-hashes --no-build` into an environment of the bundled interpreter;
only the package files are shipped. Deno and Pyodide are installed into `rt/` by the
app's own `prepare`, so the bundle and a first run share one journal.

Only the standard library is imported here, so this file runs before any dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
CORE = ROOT / "core"
BRAND_FILE = CORE / "config" / "brand.yaml"
RUNTIME_LOCK = CORE / "config" / "runtime.lock.json"
NOTICES_FILE = ROOT / "THIRD_PARTY_NOTICES.md"
PROFILE_ADAPTERS_FILE = PACKAGING / "profile-adapters.json"
CHUNK = 1 << 20
PLACEHOLDER = re.compile(r"@[A-Z_]+@")
QWEN_TTS_ITEM = "package-qwen-tts"

# The sibling module holds the FFmpeg source pins, so it is imported from its folder.
if str(PACKAGING) not in sys.path:
    sys.path.insert(0, str(PACKAGING))
import corresponding_source  # noqa: E402


class BuildError(RuntimeError):
    pass


# --- small helpers ------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    """Same bytes as `app.ports.canonical_digest` for the integer-only lock file."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_brand(path: Path = BRAND_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        key, sep, value = line.partition(":")
        if line and not line.startswith("#") and sep:
            values[key.strip()] = value.strip().strip("\"'")
    for key in ("display_name_ko", "display_name_en", "app_id"):
        if not values.get(key):
            raise BuildError(f"brand.yaml has no {key}")
    return values


def distribution_settings(profile: str, interpreter: str) -> dict[str, object]:
    """The shipped `dist.json`: the default profile input, the shared provider table and the
    aligner location (the bundled interpreter and its own site folder, relative to the bundle)."""
    source = PACKAGING / "profiles" / f"{profile}.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    if "profile_adapters" in payload:
        raise BuildError(f"{source.name} must not repeat the shared provider table")
    payload["profile_adapters"] = json.loads(PROFILE_ADAPTERS_FILE.read_text(encoding="utf-8"))
    payload["align_python"] = interpreter
    payload["align_site"] = "align-site"
    return payload


def core_version() -> str:
    data = tomllib.loads((CORE / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def host_target() -> tuple[str, str]:
    name = "windows" if sys.platform == "win32" else "linux"
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}
    machine = platform.machine().lower()
    return name, arch.get(machine, machine)


def bundle_name(
    brand: Mapping[str, str], version: str, os_name: str, arch: str, profile: str = "release"
) -> str:
    """Release files carry no profile in their name; the developer build ends in `-dev`."""
    suffix = "" if profile == "release" else f"-{profile}"
    return f"{brand['app_id']}-{version}-{os_name}-{arch}{suffix}"


def render_template(text: str, values: Mapping[str, str]) -> str:
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    left = PLACEHOLDER.findall(text)
    if left:
        raise BuildError(f"template placeholders left unfilled: {sorted(set(left))}")
    return text


def run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603 - fixed argument lists, no shell
        list(argv), text=True, capture_output=True, check=False, **kwargs  # type: ignore[arg-type]
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip()[-1500:]
        raise BuildError(f"{Path(argv[0]).name} failed ({completed.returncode}): {tail}")
    return completed


# --- notices, build info, sums ------------------------------------------------------


def render_notices(
    lock: Mapping[str, object],
    packages: Sequence[tuple[str, str, str]] = (),
    aligner_packages: Sequence[tuple[str, str, str]] = (),
) -> str:
    """Markdown notices from the runtime manifest, plus the Python packages when given."""
    lines = [
        "# Third-party notices",
        "",
        "This file is generated by `packaging/build.py notices` from the runtime manifest. "
        "Do not edit it by hand.",
        "",
        "## Runtime files",
        "",
        "These files are prepared from the runtime manifest and checked against its SHA-256 "
        "values.",
        "",
        "| Item | Version | License | Source |",
        "| --- | --- | --- | --- |",
    ]
    for item in lock["items"]:  # type: ignore[index]
        license_info = item["license"]
        lines.append(
            f"| {item['id']} | {item['version']} | {license_info['spdx']} "
            f"| {license_info['source_url']} |"
        )
    lines += corresponding_source.notice_lines()
    lines += [
        "## Bundled Python",
        "",
        "Distributions bundle a CPython build from python-build-standalone. Python and "
        "its bundled libraries keep the license files they ship with.",
        "",
        "## Python packages",
        "",
    ]
    if packages:
        lines += ["| Package | Version | License |", "| --- | --- | --- |"]
        lines += [f"| {name} | {version} | {license_text} |" for name, version, license_text in packages]
    else:
        lines.append(
            "The list of installed packages with their licenses is written into this file "
            "inside each distribution."
        )
    if aligner_packages:
        lines += [
            "",
            "## Aligner packages",
            "",
            "The aligner runs from its own folder with its own torch. These packages are "
            "not part of the list above.",
            "",
            "| Package | Version | License |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {name} | {version} | {license_text} |"
            for name, version, license_text in aligner_packages
        ]
    lines.append("")
    return "\n".join(lines)


def installed_packages(site: Path) -> list[tuple[str, str, str]]:
    found = []
    for dist in metadata.distributions(path=[str(site)]):
        meta = dist.metadata
        expression = meta.get("License-Expression") or ""
        if not expression:
            classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
            expression = "; ".join(c.rsplit("::", 1)[-1].strip() for c in classifiers)
        if not expression:
            expression = (meta.get("License") or "").splitlines()[0][:80] if meta.get("License") else ""
        found.append((str(meta["Name"]), str(meta["Version"]), expression or "see package"))
    return sorted(found, key=lambda row: row[0].lower())


def render_build_info(
    *,
    commit: str,
    os_name: str,
    arch: str,
    profile: str,
    python_version: str,
    dry_run: bool,
    lock: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build facts. `lock` is the runtime lock the distribution ships."""
    lock = lock if lock is not None else json.loads(RUNTIME_LOCK.read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "app_version": core_version(),
        "commit": commit,
        "lock_hash": sha256_file(CORE / "poetry.lock"),
        "align_lock_hash": sha256_file(CORE / "align_runtime" / "poetry.lock"),
        "runtime_manifest_digest": canonical_digest(lock),
        "profile": profile,
        "os": os_name,
        "arch": arch,
        "python": python_version,
        "dry_run": dry_run,
    }


def write_sums(files: Sequence[Path], out: Path) -> None:
    lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(files, key=lambda p: p.name)]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- bundle ---------------------------------------------------------------------------


def download_python(lock: Mapping[str, object], label: str, work: Path) -> Path:
    asset = lock["python"]["assets"][label]  # type: ignore[index]
    target = work / asset["name"]
    request = urllib.request.Request(asset["url"], headers={"User-Agent": "packaging"})
    with urllib.request.urlopen(request, timeout=600) as response, target.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out, CHUNK)
    if target.stat().st_size != asset["bytes"] or sha256_file(target) != asset["sha256"]:
        raise BuildError(f"the downloaded Python archive does not match {label} in python.lock.json")
    return target


def unpack_python(archive: Path, bundle: Path) -> None:
    with tarfile.open(archive) as tar:
        tar.extractall(bundle, filter="data")


def export_requirements(poetry: str, out: Path, project: Path = CORE) -> Path:
    run(
        [*shlex.split(poetry), "export", "--only", "main", "--format", "requirements.txt",
         "--output", str(out)],
        cwd=project,
    )
    text = out.read_text(encoding="utf-8")
    if "--hash=sha256:" not in text:
        raise BuildError("poetry export wrote no hashes")
    out.write_text(accept_windows_machine(text), encoding="utf-8")
    return out


_AMD64_MARKER = 'platform_machine == "amd64"'


def accept_windows_machine(text: str) -> str:
    """Let a marker written for `amd64` match Windows, whose machine name is `AMD64`.

    Marker strings compare case-sensitively. A package such as `hf-xet` lists only the
    lower-case name, so a Windows install would drop it and downloads would lose the
    parallel transfer; the hashes already cover its Windows wheel.
    """
    return text.replace(_AMD64_MARKER, f'{_AMD64_MARKER} or platform_machine == "AMD64"')


def create_environment(python: Path, requirements: Path, env_dir: Path) -> Path:
    """A venv of the bundled interpreter holding exactly the hashed requirements."""
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("uv is not on PATH")
    run([str(python), "-m", "venv", "--without-pip", str(env_dir)])
    env_python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    run([uv, "pip", "sync", "--require-hashes", "--no-build", "--python", str(env_python),
         str(requirements)])
    return env_python


def install_wheel(env_python: Path, wheel: Path) -> None:
    """Install one verified wheel; its dependencies are already in the environment or unwanted."""
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("uv is not on PATH")
    run([uv, "pip", "install", "--no-deps", "--no-index", "--python", str(env_python), str(wheel)])


def copy_site(env_python: Path, target: Path) -> Path:
    purelib = run(
        [str(env_python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"]
    ).stdout.strip()
    shutil.copytree(purelib, target)
    return target


def package_wheel(lock: Mapping[str, object], item_id: str, os_name: str, work: Path) -> Path:
    """Download the wheel the runtime lock pins for the item and verify size and SHA-256."""
    item = next((i for i in lock["items"] if i["id"] == item_id), None)  # type: ignore[index]
    entry = None if item is None else next(
        (f for f in item["files"] if f["os"] in (os_name, "any")), None
    )
    if entry is None:
        raise BuildError(f"the runtime lock has no wheel for {item_id}")
    target = work / entry["file"]
    request = urllib.request.Request(entry["url"], headers={"User-Agent": "packaging"})
    with urllib.request.urlopen(request, timeout=600) as response, target.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out, CHUNK)
    verify_wheel(target, entry)
    return target


def verify_wheel(path: Path, entry: Mapping[str, object]) -> None:
    if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
        raise BuildError(f"{path.name} does not match its size and SHA-256 in the lock")


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def check_no_pth(site: Path, label: str) -> None:
    """A .pth file could pull another environment onto this one's import path."""
    found = sorted(path.name for path in site.glob("*.pth"))
    if found:
        raise BuildError(f"{label} holds .pth files: {', '.join(found)}")


def check_unused_packages(site: Path, unused: Sequence[str]) -> None:
    """The alignment path imports none of these, so they must not ride along."""
    prefixes = tuple(normalized(name) for name in unused)
    found = set()
    for entry in site.iterdir():
        if entry.name.endswith(".dist-info"):
            stem = entry.name.removesuffix(".dist-info").rsplit("-", 1)[0]
        elif entry.is_dir():
            stem = entry.name
        else:
            continue
        if normalized(stem).startswith(prefixes):
            found.add(entry.name)
    if found:
        raise BuildError(f"align-site holds unused packages: {', '.join(sorted(found))}")


def check_aligner_import(python: Path, site: Path) -> None:
    """The aligner imports from its own folder alone, with the settings the app gives it."""
    env = {"PYTHONPATH": str(site), "PYTHONNOUSERSITE": "1"}
    if os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    run([str(python), "-c", "import whisperx.alignment"], env=env)


def locked_version(lock_file: Path, name: str) -> str:
    data = tomllib.loads(lock_file.read_text(encoding="utf-8"))
    for package in data["package"]:
        if package["name"] == name:
            return str(package["version"])
    raise BuildError(f"{lock_file.parent.name}/{lock_file.name} has no {name}")


def check_torch_version(site: Path, lock_file: Path, label: str) -> str:
    """The installed torch is the one the environment's own lock pins."""
    wanted = locked_version(lock_file, "torch")
    dists = [d for d in metadata.distributions(path=[str(site)]) if d.metadata["Name"] == "torch"]
    if len(dists) != 1 or dists[0].version != wanted:
        raise BuildError(f"{label} torch is not {wanted}")
    return wanted


def aligner_installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "align_install_whisperx", CORE / "align_runtime" / "install_whisperx.py"
    )
    if spec is None or spec.loader is None:
        raise BuildError("core/align_runtime/install_whisperx.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_aligner(python: Path, poetry: str, work: Path, bundle: Path) -> Path:
    """The aligner environment: its own torch, the pinned WhisperX wheel without dependencies."""
    project = CORE / "align_runtime"
    requirements = export_requirements(poetry, work / "align-requirements.txt", project)
    env_python = create_environment(python, requirements, work / "align-env")
    installer = aligner_installer()
    try:
        pin = installer.pinned()
    except SystemExit as error:
        raise BuildError(str(error)) from error
    wheel = work / pin["url"].rsplit("/", 1)[-1]
    installer.download(pin["url"], wheel)
    if not installer.verified(wheel, pin):
        raise BuildError(f"{wheel.name} does not match its size and SHA-256 in the lock")
    install_wheel(env_python, wheel)
    site = copy_site(env_python, bundle / "align-site")
    check_no_pth(site, "align-site")
    check_unused_packages(site, installer.UNUSED)
    check_torch_version(site, project / "poetry.lock", "align")
    check_aligner_import(python.resolve(), site)
    return site


def copy_core(bundle: Path) -> None:
    target = bundle / "core"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(CORE / "app", target / "app", ignore=ignore)
    shutil.copytree(CORE / "config", target / "config")
    shutil.copy2(CORE / "pyproject.toml", target / "pyproject.toml")


def ffmpeg_entry(label: str) -> tuple[dict[str, object], dict[str, object]]:
    """The FFmpeg item pinned for the target and the build entry it comes from."""
    pin = json.loads((PACKAGING / "ffmpeg.lock.json").read_text(encoding="utf-8"))
    build = pin["builds"].get(label)
    if build is None:
        raise BuildError(f"ffmpeg.lock.json has no FFmpeg build for {label}")
    return pin, build


def lock_with_ffmpeg(lock: Mapping[str, object], label: str) -> dict[str, object]:
    """The runtime lock a distribution ships: the contract lock with the pinned FFmpeg build.

    The contract lock's `ffmpeg` item serves development and CI, where `scripts/dev_setup.py`
    extracts the wheel binary. A distribution replaces it with the build pinned in
    `ffmpeg.lock.json`, so the item of the same id is dropped and exactly one remains.

    The media adapter runs only the executable that the lock names, never one from PATH.
    The entry names the downloaded archive by URL, bytes and SHA-256 and the executable by
    its path inside that archive, so the runtime preparer installs and repairs it.
    """
    pin, build = ffmpeg_entry(label)
    item = {
        "id": pin["id"],
        "version": pin["version"],
        "revision": pin["revision"],
        "install_path": pin["install_path"],
        "license": pin["license"],
        "files": [
            {
                "os": build["os"],
                "arch": build["arch"],
                "file": build["member"],
                "url": build["url"],
                "bytes": build["archive_bytes"],
                "sha256": build["archive_sha256"],
            }
        ],
    }
    items = [entry for entry in lock["items"] if entry["id"] != pin["id"]]  # type: ignore[index]
    return {**lock, "items": [*items, item]}


def copy_ffmpeg_licenses(bundle: Path, label: str) -> None:
    """Copy the notices of the archive that the ordinary runtime preparer installed."""
    pin, build = ffmpeg_entry(label)
    folder = bundle / "rt" / str(pin["install_path"])
    licenses = bundle / "licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copy2(PACKAGING / "licenses" / "GPL-3.0.txt", licenses / "FFmpeg-GPL-3.0.txt")
    for index, member in enumerate(build["license_members"]):  # type: ignore[attr-defined]
        source = folder.joinpath(*str(member).split("/"))
        if not source.is_file():
            raise BuildError(f"the FFmpeg archive has no license file {member}")
        shutil.copy2(source, licenses / f"FFmpeg-archive-{index + 1}-{source.name}")


def make_sources_archive(os_name: str, arch: str, out: Path, work: Path) -> Path:
    """Download, verify and pack the complete corresponding source for one platform.

    The archive goes to the same Release as the distribution; it is never part of the
    installed files, because the source set is about a gigabyte per platform.
    """
    label = f"{os_name}-{arch}"
    out.mkdir(parents=True, exist_ok=True)
    tree = work / "corresponding-source"
    shutil.rmtree(tree, ignore_errors=True)
    corresponding_source.stage_sources(label, tree, work)
    target = out / corresponding_source.asset_name(label)
    with tarfile.open(target, "w") as handle:
        handle.add(tree, arcname=target.stem)
    return target


def build_bundle(args: argparse.Namespace) -> Path:
    brand = read_brand()
    version = core_version()
    default_os, default_arch = host_target()
    os_name = args.os or default_os
    arch = default_arch
    label = f"{os_name}-{arch}"
    lock = json.loads((PACKAGING / "python.lock.json").read_text(encoding="utf-8"))
    interpreter = lock["python"]["assets"].get(label, {}).get("interpreter")
    if args.python_dir is None and interpreter is None:
        raise BuildError(f"python.lock.json has no Python for {label}")
    bundle = args.out.resolve() / bundle_name(brand, version, os_name, arch, args.profile)
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="bundle-") as scratch:
        work = Path(scratch)
        if args.python_dir is not None:
            shutil.copytree(args.python_dir, bundle / "python", symlinks=True)
            interpreter = "python/bin/python3.11" if os_name == "linux" else "python/python.exe"
        else:
            unpack_python(download_python(lock, label, work), bundle)
        python = bundle / interpreter
        runtime_lock = json.loads(RUNTIME_LOCK.read_text(encoding="utf-8"))
        requirements = args.requirements or export_requirements(args.poetry, work / "requirements.txt")
        env_python = create_environment(python, requirements, work / "env")
        wheel = package_wheel(runtime_lock, QWEN_TTS_ITEM, os_name, work)
        install_wheel(env_python, wheel)
        site = copy_site(env_python, bundle / "site-packages")
        check_torch_version(site, CORE / "poetry.lock", "main")
        align_site = build_aligner(python, args.poetry, work, bundle)
        copy_core(bundle)
        bundled_lock = bundle / "core" / "config" / "runtime.lock.json"
        bundled_lock.write_text(
            json.dumps(
                lock_with_ffmpeg(json.loads(bundled_lock.read_text(encoding="utf-8")), label),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        web = args.web.resolve()
        if not (web / "index.html").is_file():
            raise BuildError("the web folder has no index.html; build the frontend first")
        shutil.copytree(web, bundle / "web")
        compile_python(python, bundle)
        run(
            [str(python), str(PACKAGING / "prepare_runtime.py"), str(bundle),
             str(PACKAGING / "bundle.json")]
        )
        copy_ffmpeg_licenses(bundle, label)
        python_version = run(
            [str(python), "-c", "import platform; print(platform.python_version())"]
        ).stdout.strip()
        finish_bundle(bundle, args, os_name, arch, python_version, site, align_site, interpreter)
    return bundle


def compile_python(python: Path, bundle: Path) -> None:
    mode = ["-q", "--invalidation-mode", "unchecked-hash"]
    run([str(python), "-m", "compileall", *mode, str(bundle / "core")])
    # A third-party package may ship a file for another Python version; that is not fatal.
    for folder in ("site-packages", "align-site"):
        subprocess.run(  # noqa: S603
            [str(python), "-m", "compileall", *mode, str(bundle / folder)],
            capture_output=True, check=False,
        )


def finish_bundle(
    bundle: Path,
    args: argparse.Namespace,
    os_name: str,
    arch: str,
    python_version: str,
    site: Path,
    align_site: Path,
    interpreter: str,
) -> None:
    shutil.copy2(PACKAGING / "launch.py", bundle / "launch.py")
    if os_name == "linux":
        start = bundle / "start.sh"
        shutil.copy2(PACKAGING / "start.sh", start)
        start.chmod(0o755)
    (bundle / "dist.json").write_text(
        json.dumps(distribution_settings(args.profile, interpreter), indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
    lock = json.loads((bundle / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    (bundle / "THIRD_PARTY_NOTICES.md").write_text(
        render_notices(lock, installed_packages(site), installed_packages(align_site)),
        encoding="utf-8",
    )
    commit = args.commit or os.environ.get("GITHUB_SHA") or git_commit()
    info = render_build_info(
        commit=commit, os_name=os_name, arch=arch, profile=args.profile,
        python_version=python_version, dry_run=args.python_dir is not None, lock=lock,
    )
    (bundle / "build-info.json").write_text(
        json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def git_commit() -> str:
    try:
        return run(["git", "rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
    except (BuildError, OSError):
        return "unknown"


# --- archive --------------------------------------------------------------------------


def make_tarball(bundle: Path, out: Path) -> Path:
    target = out / f"{bundle.name}.tar.gz"
    with tarfile.open(target, "w:gz", compresslevel=6) as tar:
        tar.add(bundle, arcname=bundle.name)
    return target


def find_iscc() -> str | None:
    found = shutil.which("iscc") or shutil.which("ISCC.exe")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base and (Path(base) / "Inno Setup 6" / "ISCC.exe").is_file():
            return str(Path(base) / "Inno Setup 6" / "ISCC.exe")
    return None


def render_installer_script(brand: Mapping[str, str], version: str, bundle: Path, out: Path) -> str:
    template = (PACKAGING / "installer.iss.in").read_text(encoding="utf-8")
    return render_template(
        template,
        {
            "APP_ID": brand["app_id"],
            "DISPLAY_NAME": brand["display_name_ko"],
            "VERSION": version,
            "BUNDLE_DIR": str(bundle),
            "OUTPUT_DIR": str(out),
            "OUTPUT_NAME": f"{bundle.name}-setup",
        },
    )


def make_windows_installer(bundle: Path, out: Path) -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise BuildError("Inno Setup (ISCC.exe) is not installed")
    script = render_installer_script(read_brand(), core_version(), bundle, out)
    script_path = out / "installer.iss"
    script_path.write_text(script, encoding="utf-8-sig")
    run([iscc, "/Q", str(script_path)])
    setup = out / f"{bundle.name}-setup.exe"
    if not setup.is_file():
        raise BuildError("Inno Setup did not write the installer")
    return setup


# --- command line ---------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    bundle = sub.add_parser("bundle", help="build the bundle folder")
    bundle.add_argument("--os", choices=("linux", "windows"))
    bundle.add_argument("--profile", choices=("release", "dev"), required=True)
    bundle.add_argument("--out", type=Path, required=True)
    bundle.add_argument("--web", type=Path, required=True, help="built frontend folder")
    bundle.add_argument("--poetry", default="poetry", help="command that runs poetry export")
    bundle.add_argument("--requirements", type=Path, help="use this hashed list, skip export")
    bundle.add_argument("--commit", help="commit recorded in build-info.json")
    bundle.add_argument(
        "--python-dir", type=Path,
        help="host check only: use this interpreter folder instead of the pinned download",
    )
    archive = sub.add_parser("archive", help="tarball (linux) or installer (windows)")
    archive.add_argument("--os", choices=("linux", "windows"), required=True)
    archive.add_argument("--bundle", type=Path, required=True)
    archive.add_argument("--out", type=Path, required=True)
    notices = sub.add_parser("notices", help="write or check THIRD_PARTY_NOTICES.md")
    notices.add_argument("--check", action="store_true")
    sources = sub.add_parser("sources", help="corresponding-source archive for one platform")
    sources.add_argument("--os", choices=("linux", "windows"), required=True)
    sources.add_argument("--arch", default="x86_64")
    sources.add_argument("--out", type=Path, required=True)
    sources.add_argument("--work", type=Path, help="keep verified downloads in this folder")
    sums = sub.add_parser("sums", help="write SHA256SUMS for the given files")
    sums.add_argument("files", nargs="+", type=Path)
    sums.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "bundle":
            print(build_bundle(args))
        elif args.command == "archive":
            args.out.mkdir(parents=True, exist_ok=True)
            maker = make_tarball if args.os == "linux" else make_windows_installer
            print(maker(args.bundle.resolve(), args.out.resolve()))
        elif args.command == "notices":
            text = render_notices(
                lock_with_ffmpeg(
                    json.loads(RUNTIME_LOCK.read_text(encoding="utf-8")), "linux-x86_64"
                )
            )
            if args.check:
                if not NOTICES_FILE.is_file() or NOTICES_FILE.read_text(encoding="utf-8") != text:
                    raise BuildError("THIRD_PARTY_NOTICES.md is out of date; run notices")
            else:
                NOTICES_FILE.write_text(text, encoding="utf-8")
        elif args.command == "sources":
            with tempfile.TemporaryDirectory(prefix="sources-") as scratch:
                work = args.work or Path(scratch)
                print(make_sources_archive(args.os, args.arch, args.out.resolve(), work))
        else:
            write_sums(args.files, args.out)
    except (BuildError, corresponding_source.SourceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
