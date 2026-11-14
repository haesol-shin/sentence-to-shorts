"""The app tree follows the static import rules, and the checker catches violations."""

from __future__ import annotations

from pathlib import Path

from tests.architecture.import_rules import check_tree

CORE = Path(__file__).resolve().parents[2]
APP = CORE / "app"
VIOLATIONS = Path(__file__).resolve().parent / "fixtures" / "violations"


def test_supported_top_level_packages() -> None:
    from tests.architecture.import_rules import APPROVED_TOP_LEVEL

    found = {
        path.name[:-3] if path.suffix == ".py" else path.name
        for path in APP.iterdir()
        if path.name != "__pycache__"
    }
    assert found == set(APPROVED_TOP_LEVEL)


def test_app_tree_has_no_import_violations() -> None:
    assert check_tree(APP) == []


def test_checker_catches_each_violation() -> None:
    messages = "\n".join(check_tree(VIOLATIONS))
    assert "imports settings outside bootstrap" in messages
    assert "routers/relative_settings.py: imports settings outside bootstrap" in messages
    assert "routers/from_app_settings.py: imports settings outside bootstrap" in messages
    assert "provider SDK" in messages
    assert "dynamic import" in messages
    assert "not approved" in messages
