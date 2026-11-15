"""Storage roots per OS, APP_* overrides and the short layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.paths import Layout, default_roots, resolve_roots

PROJECT_ID = "p_06pxfteaw88hs93kkckw5j51ng"
VIDEO_ID = "v_0hzb7bexv28termtt2ypc6trzt"
ARTIFACT_ID = "a_01jg7w6q3z8k4m2v9x5b7c1d3e"


def test_roots_default_per_os(tmp_path: Path) -> None:
    home = tmp_path / "home"
    linux = default_roots("app", env={}, platform="linux", home=home)
    assert linux.data == home / ".local" / "share" / "app"
    assert linux.cache == home / ".cache" / "app"
    assert linux.model == linux.data / "models"

    xdg = default_roots(
        "app",
        env={"XDG_DATA_HOME": str(tmp_path / "xd"), "XDG_CACHE_HOME": "relative"},
        platform="linux",
        home=home,
    )
    assert xdg.data == tmp_path / "xd" / "app"
    assert xdg.cache == home / ".cache" / "app"

    local = tmp_path / "Local"
    windows = default_roots(
        "app", env={"LOCALAPPDATA": str(local)}, platform="win32", home=home
    )
    assert (windows.data, windows.cache) == (local / "app" / "data", local / "app" / "cache")
    assert windows.model == local / "app" / "data" / "models"


def test_roots_env_overrides_each_root(tmp_path: Path) -> None:
    env = {
        "APP_DATA_DIR": str(tmp_path / "d"),
        "APP_CACHE_DIR": str(tmp_path / "c"),
        "APP_RUNTIME_DIR": str(tmp_path / "r"),
    }
    roots = resolve_roots("app", env=env, platform="linux", home=tmp_path)
    assert roots.data == tmp_path / "d"
    assert roots.cache == tmp_path / "c"
    assert roots.model == tmp_path / "d" / "models"
    assert roots.runtime == tmp_path / "r"
    env["APP_MODEL_DIR"] = str(tmp_path / "m")
    assert resolve_roots("app", env=env, platform="linux", home=tmp_path).model == tmp_path / "m"


def test_layout_paths_stay_short_and_inside_root(tmp_path: Path) -> None:
    layout = Layout(data=tmp_path / "d", cache=tmp_path / "c")
    below_data = [
        layout.revision_file(PROJECT_ID, VIDEO_ID, 9999),
        layout.output_file(VIDEO_ID, ARTIFACT_ID, "mp4"),
        layout.project_file(PROJECT_ID),
    ]
    for path in below_data:
        assert len(path.relative_to(layout.data).as_posix()) <= 80
    assert len(Layout.cache_artifact("f" * 64, ARTIFACT_ID, "json")) <= 80
    for bad in ("../p", "p_x", PROJECT_ID + "/.."):
        with pytest.raises(ValueError):
            layout.project_dir(bad)
