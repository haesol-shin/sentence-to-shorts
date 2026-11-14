"""Static import rules that import-linter cannot express.

Checks:
- only approved top-level packages under app/
- app.settings is imported only by bootstrap
- provider SDKs are imported only under llm/providers
- dynamic imports only in the plugin registry
"""

from __future__ import annotations

import ast
from pathlib import Path

APPROVED_TOP_LEVEL = frozenset(
    {
        "__init__",
        "__main__",
        "access",
        "bootstrap",
        "catalog",
        "jobs",
        "llm",
        "main",
        "plugins",
        "ports",
        "routers",
        "runtime",
        "schemas",
        "services",
        "settings",
        "storage",
        "tools",
    }
)
PROVIDER_SDKS = frozenset({"anthropic", "openai", "cohere", "mistralai", "google"})
PROVIDER_PREFIX = ("llm", "providers")
REGISTRY_PATH = "plugins/registry.py"
BOOTSTRAP_PATH = "bootstrap.py"


def _dynamic_import(node: ast.Call) -> bool:
    function = node.func
    if isinstance(function, ast.Name) and function.id == "__import__":
        return True
    return (
        isinstance(function, ast.Attribute)
        and function.attr in ("import_module", "reload")
        and isinstance(function.value, ast.Name)
        and function.value.id == "importlib"
    )


def _imported_modules(node: ast.AST, relative: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    if node.level:
        package = list(relative.parent.parts)
        if node.level > 1:
            package = package[: -(node.level - 1)]
        base = ".".join(["app", *package, *([node.module] if node.module else [])])
    else:
        base = node.module or ""
    modules = [base] if base else []
    modules.extend(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    return modules


def check_tree(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        parts = relative.parts
        top = parts[0] if len(parts) > 1 else path.stem
        if top not in APPROVED_TOP_LEVEL:
            violations.append(f"{relative.as_posix()}: top-level package {top!r} is not approved")
        inside_providers = len(parts) >= 3 and parts[:2] == PROVIDER_PREFIX
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            violations.append(f"{relative.as_posix()}: cannot parse ({error})")
            continue
        for node in ast.walk(tree):
            for module in _imported_modules(node, relative):
                if (module == "app.settings" or module.startswith("app.settings.")) and (
                    relative.as_posix() != BOOTSTRAP_PATH
                ):
                    violations.append(f"{relative.as_posix()}: imports settings outside bootstrap")
                if module.split(".")[0] in PROVIDER_SDKS and not inside_providers:
                    violations.append(
                        f"{relative.as_posix()}: provider SDK import outside llm/providers"
                    )
            if isinstance(node, ast.Call) and _dynamic_import(node):
                if relative.as_posix() != REGISTRY_PATH:
                    violations.append(f"{relative.as_posix()}: dynamic import outside the registry")
    return violations
