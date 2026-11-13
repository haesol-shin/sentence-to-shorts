#!/usr/bin/env python3
"""Check that public documents are safe to publish and follow the Markdown rules.

Checks, in order:
1. Public text (every Markdown file, workflows, cubic.yaml) has no internal path,
   personal quote, or personal tool name.
2. Markdown paragraphs and list items are written on one line (no soft line
   break) and contain no em-dash. Code blocks, tables, HTML blocks, front matter
   and deliberate hard breaks are not checked.
3. Relative links and heading anchors in Markdown files resolve.
4. Every ADR file under docs/decisions/ is listed in its index.

Needs markdown-it-py. Run it in an isolated environment:
    uv run --with markdown-it-py==3.0.0 python scripts/check_public_docs.py [--root DIR]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

from check_brand import list_files

EM_DASH = "\u2014"
# Generated files are not hand-written, so the writing rules skip them.
GENERATED_PREFIXES = ("frontend/src/shared/api/generated/",)
SKIP_PARTS = {".git", ".local", ".venv", "node_modules"}
WORKFLOW_SUFFIXES = (".yml", ".yaml")

# Bracketed first letters keep this file from matching its own patterns.
TERMS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern))
    for label, pattern in (
        ("internal path", r"/[h]ome/\w"),
        ("internal path", r"[H]omebase"),
        ("internal path", r"[1]0_Active"),
        ("internal path", r"[0]0_Inbox"),
        ("internal path", r"[s]eafile"),
        ("internal path", r"research-\d"),
        ("internal document", r"[H]ANDOFF"),
        ("internal document", r"[o]ps-and-gaps"),
        ("internal document", r"[a]dr-sources"),
        ("internal document", r"(?:glossary|structure|release-dev)-draft"),
        ("internal task id", r"\bK0[a-z]\d?\b"),
        ("personal tool", r"[t]askwatch"),
        ("personal tool", r"\b[o]mp\b"),
        ("personal tool", r"[H]ermes"),
        ("personal tool", r"\b[r]eceipt\b"),
        ("personal tool", r"\b[l]and\b"),
        ("personal tool", r"@[t]ask\b"),
        ("personal tool", r"@[s]low\b"),
        ("development agent", r"[C]odex"),
        ("development agent", r"\b[G]PT-\d"),
        ("personal quote", r"[T]elegram|텔레그램"),
        ("personal quote", r"해솔"),
        ("personal quote", r"(?:사용자|소유자)\s*\d{1,2}/\d{1,2}"),
        ("personal quote", r"(?:사용자|소유자)\s*「"),
        ("personal quote", r"(?:결정|확인)\(\s*(?:사용자|소유자|\d{4}-\d{2}-\d{2})"),
        ("conversation date", r"\d{1,2}/\d{1,2}\s*「"),
        ("conversation date", r"\d{4}-\d{2}-\d{2}\s*「"),
        ("conversation date", r"(?<![\d/])\d{1,2}/\d{1,2}\([월화수목금토일]\)"),
    )
)

LINK_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//")
ADR_FILE = re.compile(r"^\d{4}-[a-z0-9-]+\.md$")


def make_parser() -> MarkdownIt:
    return MarkdownIt("commonmark").enable("table")


def blank_front_matter(text: str) -> str:
    """Replace a leading front matter block with blank lines to keep line numbers."""
    lines = text.split("\n")
    if lines and lines[0].rstrip() == "---":
        for end in range(1, len(lines)):
            if lines[end].rstrip() == "---":
                lines[: end + 1] = [""] * (end + 1)
                break
    return "\n".join(lines)


def is_generated(rel: str) -> bool:
    return rel.startswith(GENERATED_PREFIXES)


def public_text_files(files: list[str]) -> list[str]:
    selected = []
    for rel in files:
        parts = rel.split("/")
        if SKIP_PARTS.intersection(parts) or is_generated(rel):
            continue
        if rel.endswith(".md") or rel == "cubic.yaml":
            selected.append(rel)
        elif rel.startswith(".github/") and rel.endswith(WORKFLOW_SUFFIXES):
            selected.append(rel)
    return selected


def check_terms(rel: str, text: str) -> list[str]:
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in TERMS:
            match = pattern.search(line)
            if match:
                problems.append(f"{rel}:{number}: {label} in public text ({match.group(0)!r})")
                break
    return problems


def heading_slug(text: str) -> str:
    """GitHub-style anchor: lower case, drop punctuation, spaces to hyphens."""
    kept = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return kept.replace(" ", "-")


def inline_text(tok) -> str:
    return "".join(c.content for c in (tok.children or []) if c.type in ("text", "code_inline"))


def heading_anchors(tokens) -> set[str]:
    seen: dict[str, int] = {}
    anchors = set()
    for index, tok in enumerate(tokens):
        if tok.type == "heading_open":
            slug = heading_slug(inline_text(tokens[index + 1]))
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def check_markdown(rel: str, tokens) -> list[str]:
    """Soft line breaks and em-dashes in paragraphs, list items and headings."""
    problems = []
    table_depth = 0
    for tok in tokens:
        if tok.type == "table_open":
            table_depth += 1
        elif tok.type == "table_close":
            table_depth -= 1
        elif tok.type == "inline" and table_depth == 0 and tok.map:
            line = tok.map[0] + 1
            for child in tok.children or []:
                if child.type == "softbreak":
                    problems.append(f"{rel}:{line}: soft line break inside a paragraph or list item")
                    line += 1
                elif child.type == "hardbreak":
                    line += 1
                elif child.type == "text" and EM_DASH in child.content:
                    problems.append(f"{rel}:{line}: em-dash")
    return problems


def link_targets(tokens):
    for tok in tokens:
        if tok.type != "inline":
            continue
        line = (tok.map[0] + 1) if tok.map else 0
        for child in tok.children or []:
            if child.type == "softbreak" or child.type == "hardbreak":
                line += 1
            elif child.type == "link_open":
                yield line, child.attrGet("href") or ""
            elif child.type == "image":
                yield line, child.attrGet("src") or ""


def check_links(root: Path, rel: str, tokens, anchors: dict[str, set[str]], parser: MarkdownIt) -> list[str]:
    problems = []
    base = (root / rel).parent
    for line, href in link_targets(tokens):
        if not href or LINK_SCHEME.match(href):
            continue
        path_part, _, fragment = href.partition("#")
        path_part = unquote(path_part.partition("?")[0])
        target = (base / path_part).resolve() if path_part else root / rel
        try:
            target.relative_to(root.resolve())
        except ValueError:
            problems.append(f"{rel}:{line}: link leaves the repository ({href})")
            continue
        if not target.exists():
            problems.append(f"{rel}:{line}: broken relative link ({href})")
            continue
        if fragment and target.is_file() and target.suffix == ".md":
            key = target.as_posix()
            if key not in anchors:
                text = blank_front_matter(target.read_text(encoding="utf-8"))
                anchors[key] = heading_anchors(parser.parse(text))
            if unquote(fragment).lower() not in anchors[key]:
                problems.append(f"{rel}:{line}: missing anchor in link ({href})")
    return problems


def check_adr_index(root: Path, files: list[str]) -> list[str]:
    index_rel = "docs/decisions/README.md"
    if index_rel not in files:
        return []
    index = (root / index_rel).read_text(encoding="utf-8")
    problems = []
    for rel in files:
        name = rel.removeprefix("docs/decisions/")
        if rel.startswith("docs/decisions/") and "/" not in name and ADR_FILE.match(name) and name not in index:
            problems.append(f"{index_rel}: {name} is not listed in the index")
    return problems


def check(root: Path) -> list[str]:
    files = list_files(root)
    parser = make_parser()
    problems: list[str] = []
    anchors: dict[str, set[str]] = {}
    for rel in public_text_files(files):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        problems += check_terms(rel, text)
        if rel.endswith(".md"):
            tokens = parser.parse(blank_front_matter(text))
            problems += check_markdown(rel, tokens)
            problems += check_links(root, rel, tokens, anchors, parser)
    problems += check_adr_index(root, files)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    problems = check(args.root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_public_docs: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("check_public_docs: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
