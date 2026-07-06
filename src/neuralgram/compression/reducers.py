"""C3 deterministic reducers: token-cutting transforms with no model calls.

All reducers are pure text→text functions. Truncation operates on grapheme
clusters (`\\X`), never splitting multibyte sequences (spec C3:
grapheme-safe).
"""

import html
import re

import regex

from neuralgram.memory.chunker import estimate_tokens

_BLOCK_TAGS = re.compile(r"</?(p|div|section|article|br|tr|table|ul|ol|h[1-6])[^>]*>", re.I)
_LI_TAG = re.compile(r"<li[^>]*>", re.I)
_A_TAG = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_HEADING_TAG = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.I | re.S)
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_ANY_TAG = re.compile(r"<[^>]+>")


def html_to_md(text: str) -> str:
    """Convert HTML to plain Markdown-ish text: headings, links, list items survive."""
    text = _SCRIPT_STYLE.sub("", text)
    text = _HEADING_TAG.sub(lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2) + "\n", text)
    text = _A_TAG.sub(lambda m: f"[{m.group(2).strip()}]({m.group(1)})", text)
    text = _LI_TAG.sub("\n- ", text)
    text = _BLOCK_TAGS.sub("\n", text)
    text = _ANY_TAG.sub("", text)
    return html.unescape(text)


def dedup_lines(text: str) -> str:
    """Drop exact duplicate non-blank lines, keeping first occurrences in order."""
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.split("\n"):
        key = line.strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kept.append(line)
    return "\n".join(kept)


def fold_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs and 3+ newlines; trim line ends."""
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def drop_regex(text: str, patterns: list[str]) -> str:
    """Remove lines matching any of `patterns` (used for boilerplate)."""
    compiled = [re.compile(p) for p in patterns]
    kept = [line for line in text.split("\n") if not any(c.search(line) for c in compiled)]
    return "\n".join(kept)


def truncate_to_tokens(text: str, budget: int) -> str:
    """Grapheme-safe head truncation to ~`budget` tokens (4 chars/token heuristic)."""
    budget_chars = budget * 4
    if len(text) <= budget_chars:
        return text
    clusters = regex.findall(r"\X", text)
    out: list[str] = []
    used = 0
    for cluster in clusters:
        if used + len(cluster) > budget_chars:
            break
        out.append(cluster)
        used += len(cluster)
    return "".join(out).rstrip()


__all__ = [
    "dedup_lines",
    "drop_regex",
    "estimate_tokens",
    "fold_whitespace",
    "html_to_md",
    "truncate_to_tokens",
]
