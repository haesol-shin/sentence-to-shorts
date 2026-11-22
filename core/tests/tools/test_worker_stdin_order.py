"""No tool worker starts its stdin reader before its load is over.

On Windows a pending synchronous read on the stdin pipe can block the torch import in the main
thread, so the worker never reports `ready`. Every `serve()` must send `ready` before it names
the reader, and nothing outside the reader function may touch `sys.stdin`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "app" / "tools"
WORKERS = sorted(TOOLS.glob("**/worker.py"))
READER = "_read_requests"


def _ready_line(serve: ast.FunctionDef) -> int | None:
    lines = [
        node.lineno
        for node in ast.walk(serve)
        if isinstance(node, ast.Constant) and node.value == "ready"
    ]
    return min(lines, default=None)


def _stdin_uses(tree: ast.Module) -> list[tuple[str, int]]:
    uses: list[tuple[str, int]] = []

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef) else owner
            if (
                isinstance(child, ast.Attribute)
                and child.attr == "stdin"
                and isinstance(child.value, ast.Name)
                and child.value.id == "sys"
            ):
                uses.append((owner, child.lineno))
            visit(child, name)

    visit(tree, "<module>")
    return uses


def test_worker_stdin_order_finds_both_workers() -> None:
    names = {path.parent.name for path in WORKERS}
    assert {"align", "qwen3_tts_0_6b"} <= names


@pytest.mark.parametrize("path", WORKERS, ids=lambda path: path.parent.name)
def test_worker_stdin_order_starts_the_reader_after_ready(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    serves = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "serve"
    ]
    assert len(serves) == 1, f"{path.name} needs one module-level serve()"
    serve = serves[0]
    ready = _ready_line(serve)
    assert ready is not None, "serve() never sends `ready`"
    named = [
        node.lineno
        for node in ast.walk(serve)
        if isinstance(node, ast.Name) and node.id == READER
    ]
    assert named, f"serve() never starts {READER}"
    assert min(named) > ready, f"{READER} is named at line {min(named)}, before `ready` at {ready}"
    assert all(owner == READER for owner, _ in _stdin_uses(tree)), _stdin_uses(tree)
