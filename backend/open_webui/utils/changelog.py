"""Parse ``CHANGELOG.md`` into the JSON shape served by ``/api/changelog``.

The changelog only needs the most recent releases for the "What's New" dialog,
so the default image generates ``latest-changelog.json`` at build time with a
small stdlib-only parser.  Runtime then only has to read a small JSON file —
``beautifulsoup4`` and ``Markdown`` are no longer runtime dependencies.

The module doubles as a CLI so the Docker build (and local development) can
regenerate the file:

    python backend/open_webui/utils/changelog.py CHANGELOG.md > latest-changelog.json
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_LIMIT = 10

_VERSION_RE = re.compile(r'^##\s+\[?([^\]]+?)\]?\s*-\s*(.+?)\s*$')
_SECTION_RE = re.compile(r'^###\s+(.+?)\s*$')
_ENTRY_RE = re.compile(r'^[-*]\s+(.*)$')

_CODE_RE = re.compile(r'`([^`]+)`')
_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^)\s]+)\)')
_AUTOLINK_RE = re.compile(r'<(https?://[^>\s]+)>')
_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_STRIKE_RE = re.compile(r'~~(.+?)~~')
_ITALIC_RE = re.compile(r'(?<![\w*])\*([^*\n]+)\*(?!\*)')
_TAG_RE = re.compile(r'<[^>]+>')


def _inline_markdown(text: str) -> str:
    """Render the inline markdown subset used by the changelog as HTML."""
    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f'\x00{len(placeholders) - 1}\x00'

    def code(match: re.Match) -> str:
        return stash(f'<code>{html.escape(match.group(1))}</code>')

    def link(match: re.Match) -> str:
        href = html.escape(match.group(2), quote=True)
        label = html.escape(match.group(1))
        return stash(f'<a href="{href}">{label}</a>')

    def autolink(match: re.Match) -> str:
        href = html.escape(match.group(1), quote=True)
        return stash(f'<a href="{href}">{href}</a>')

    text = _CODE_RE.sub(code, text)
    text = _LINK_RE.sub(link, text)
    text = _AUTOLINK_RE.sub(autolink, text)

    text = html.escape(text)
    text = _BOLD_RE.sub(lambda m: f'<strong>{m.group(1)}</strong>', text)
    text = _STRIKE_RE.sub(lambda m: f'<s>{m.group(1)}</s>', text)
    text = _ITALIC_RE.sub(lambda m: f'<em>{m.group(1)}</em>', text)

    for index, value in enumerate(placeholders):
        text = text.replace(f'\x00{index}\x00', value)
    return text


def _entry_payload(body_html: str) -> dict[str, str]:
    raw = f'<li>{body_html}</li>'
    text = _TAG_RE.sub('', raw)
    text = html.unescape(text).strip()
    title, separator, content = text.partition(': ')
    if not separator:
        return {'title': '', 'content': text, 'raw': raw}
    return {'title': title.strip(), 'content': content.strip(), 'raw': raw}


def parse_changelog(content: str, limit: int | None = DEFAULT_LIMIT) -> dict[str, Any]:
    """Return ``{version: {date, section: [entries]}}`` for the newest versions."""
    changelog: dict[str, Any] = {}
    version: str | None = None
    section: str | None = None
    versions_seen = 0

    for line in content.splitlines():
        version_match = _VERSION_RE.match(line)
        if version_match:
            version = version_match.group(1).strip()
            if limit is not None and versions_seen >= limit:
                break
            changelog[version] = {'date': version_match.group(2).strip()}
            section = None
            versions_seen += 1
            continue

        if version is None:
            continue

        section_match = _SECTION_RE.match(line)
        if section_match:
            section = section_match.group(1).strip().lower()
            changelog[version][section] = []
            continue

        entry_match = _ENTRY_RE.match(line)
        if entry_match and section:
            changelog[version][section].append(_entry_payload(_inline_markdown(entry_match.group(1).strip())))

    return changelog


def load_changelog(path: str | Path, limit: int | None = DEFAULT_LIMIT) -> dict[str, Any]:
    """Parse a raw ``CHANGELOG.md`` file (source checkouts)."""
    return parse_changelog(Path(path).read_text(encoding='utf-8'), limit=limit)


def load_changelog_json(path: str | Path) -> dict[str, Any]:
    """Load the JSON produced by the build-time CLI (``main``).

    The generated file already has the ``{version: {date, section: [...]}}``
    shape, so it must be loaded with ``json.loads`` — *not* fed through
    ``parse_changelog``, which expects Markdown.
    """
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('changelog JSON must contain an object')
    return data


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    source = Path(argv[0])
    limit = int(argv[1]) if len(argv) > 1 else DEFAULT_LIMIT
    json.dump(load_changelog(source, limit=limit), sys.stdout, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
