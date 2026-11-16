"""Exercise the change-to-test map and its checked-in entries."""

from __future__ import annotations

import ast
import io
import unittest
from pathlib import Path

import _helpers  # noqa: F401  (puts scripts/ on sys.path)
import select_tests


def mapping(**changes) -> select_tests.TestMap:
    values = {
        "always": ("tests/contracts", "tests/architecture"),
        "folders": {},
        "no_core_tests": (),
    }
    values.update(changes)
    return select_tests.TestMap(**values)


class SelectTestsTest(unittest.TestCase):
    def test_mapped_folder_selects_always_and_mapped_folders(self):
        chosen = mapping(folders={"core/app/story/": ("tests/story", "tests/pipeline")})
        self.assertEqual(
            select_tests.select_tests(["core/app/story/script.py"], chosen),
            ["tests/architecture", "tests/contracts", "tests/pipeline", "tests/story"],
        )

    def test_deepest_folder_wins(self):
        chosen = mapping(
            folders={
                "core/app/plugins/": ("tests/plugins",),
                "core/app/plugins/voices/": ("tests/voice",),
            }
        )
        self.assertEqual(
            select_tests.select_tests(["core/app/plugins/voices/manifest.json"], chosen),
            ["tests/architecture", "tests/contracts", "tests/voice"],
        )

    def test_unlisted_path_selects_the_full_suite(self):
        for path in ("core/app/settings.py", "core/app/schemas/api.py", "core/pyproject.toml"):
            with self.subTest(path=path):
                self.assertEqual(
                    select_tests.select_tests([path], mapping()), [select_tests.FULL_SUITE]
                )

    def test_unlisted_path_overrides_a_mapped_path(self):
        chosen = mapping(folders={"core/app/story/": ("tests/story",)})
        self.assertEqual(
            select_tests.select_tests(["core/app/story/script.py", "core/config/app.yaml"], chosen),
            [select_tests.FULL_SUITE],
        )

    def test_paths_without_core_tests_keep_only_the_always_folders(self):
        chosen = mapping(no_core_tests=("docs/", "frontend/", "CONTRIBUTING.md"))
        for path in ("docs/CONTRACTS.md", "frontend/src/main.tsx", "CONTRIBUTING.md"):
            with self.subTest(path=path):
                self.assertEqual(
                    select_tests.select_tests([path], chosen),
                    ["tests/architecture", "tests/contracts"],
                )

    def test_blank_lines_and_the_empty_change_list_keep_the_always_folders(self):
        self.assertEqual(
            select_tests.select_tests(["", "  "], mapping()),
            ["tests/architecture", "tests/contracts"],
        )


class CheckedInMapTest(unittest.TestCase):
    def test_map_entries_exist_in_the_repository(self):
        root = Path(__file__).resolve().parents[2]
        checked = select_tests.TestMap.load()
        for target in checked.always:
            self.assertTrue((root / "core" / target).is_dir(), target)
        for entry, targets in checked.folders.items():
            path = root / entry.rstrip("/")
            if entry.endswith("/"):
                self.assertTrue(path.is_dir(), entry)
            else:
                self.assertTrue(path.is_file(), entry)
            for target in targets:
                self.assertTrue((root / "core" / target).is_dir(), target)
        for entry in checked.no_core_tests:
            self.assertTrue((root / entry.rstrip("/")).exists(), entry)

    def test_every_core_test_folder_selects_its_own_tests(self):
        root = Path(__file__).resolve().parents[2]
        checked = select_tests.TestMap.load()
        for folder in sorted((root / "core/tests").iterdir()):
            if not folder.is_dir() or not any(folder.glob("test_*.py")):
                continue
            with self.subTest(folder=folder.name):
                self.assertEqual(
                    select_tests.select_tests(
                        [f"core/tests/{folder.name}/test_sample.py"], checked
                    ),
                    sorted({f"tests/{folder.name}", *checked.always}),
                )

    def test_a_shared_test_harness_file_selects_the_full_suite(self):
        checked = select_tests.TestMap.load()
        self.assertEqual(
            select_tests.select_tests(["core/tests/conftest.py"], checked),
            [select_tests.FULL_SUITE],
        )

    def test_repository_tooling_selects_only_the_always_folders(self):
        checked = select_tests.TestMap.load()
        self.assertEqual(
            select_tests.select_tests(["scripts/select_tests.py"], checked),
            sorted(checked.always),
        )


def app_modules(path: Path) -> set[str]:
    """Return the app modules a test file imports, expanding `from app.x import y`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {module for module in modules if module.startswith("app.")}


def area_of(module: str, app_root: Path) -> str | None:
    """Return the file or folder under `app_root` that holds the imported module."""
    parts = module.split(".")
    area = None
    for end in range(2, len(parts) + 1):
        candidate = app_root.joinpath(*parts[1:end])
        if candidate.is_dir():
            area = candidate
        elif candidate.with_suffix(".py").is_file():
            area = candidate.with_suffix(".py")
        else:
            break
    return None if area is None else area.relative_to(app_root).as_posix()


class TargetOutputTest(unittest.TestCase):
    def test_targets_end_with_bare_line_feeds(self):
        class Stdout:
            def __init__(self):
                self.buffer = io.BytesIO()

        stream = Stdout()
        select_tests.write_targets(["tests/architecture", "tests/tools"], stream)
        self.assertEqual(stream.buffer.getvalue(), b"tests/architecture\ntests/tools\n")

    def test_a_text_stream_without_a_buffer_gets_one_line_per_target(self):
        stream = io.StringIO()
        select_tests.write_targets(["tests/tools"], stream)
        self.assertEqual(stream.getvalue(), "tests/tools\n")


class ConsumerCoverageTest(unittest.TestCase):
    """A map entry must name every test folder whose files import that area."""

    # The sandbox tests run in their own job, and the always folders run on every
    # pull request, so an entry does not repeat them.
    covered_elsewhere = {"tests/contracts", "tests/sandbox"}

    def test_notices_file_selects_the_packaging_tests(self):
        checked = select_tests.TestMap.load()
        self.assertIn(
            "tests/runtime", select_tests.select_tests(["THIRD_PARTY_NOTICES.md"], checked)
        )

    def test_every_importer_of_a_mapped_area_is_selected(self):
        root = Path(__file__).resolve().parents[2]
        checked = select_tests.TestMap.load()
        importers: dict[str, set[str]] = {}
        for path in (root / "core/tests").rglob("*.py"):
            relative = path.relative_to(root / "core/tests")
            if len(relative.parts) == 1 or relative.parts[0] == "fixtures":
                continue
            for module in app_modules(path):
                area = area_of(module, root / "core/app")
                if area is not None:
                    importers.setdefault(area, set()).add("tests/" + relative.parts[0])
        for entry, targets in checked.folders.items():
            if not entry.startswith("core/app/"):
                continue
            area = entry[len("core/app/") :].rstrip("/")
            inside = {
                folder
                for imported, folders in importers.items()
                for folder in folders
                if imported == area or imported.startswith(area + "/")
            }
            missing = inside - set(targets) - self.covered_elsewhere
            self.assertEqual(missing, set(), f"{entry} misses {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
