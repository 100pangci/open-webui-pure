"""Tests for the stdlib changelog parser used by ``/api/changelog``."""

from open_webui.utils.changelog import parse_changelog

SAMPLE = """# Changelog

Intro text that must be ignored.

## [1.2.0] - 2026-01-02

### Added

- ✨ **New thing.** Something with a [link](https://example.com/a) and `code`.
- Plain entry with an <b>html tag</b> and *italic*.

### Fixed

- 🐛 Fixed a bug with 1 < 2 and a <script>alert(1)</script> tag.

## [1.1.0] - 2025-12-01

### Removed

- Old thing.
"""


def test_version_and_sections():
    data = parse_changelog(SAMPLE)
    assert list(data) == ['1.2.0', '1.1.0']
    assert data['1.2.0']['date'] == '2026-01-02'
    assert set(data['1.2.0']) == {'date', 'added', 'fixed'}
    assert len(data['1.2.0']['added']) == 2
    assert data['1.1.0']['removed'][0]['raw'].startswith('<li>Old thing.</li>')


def test_limit_keeps_newest_versions():
    data = parse_changelog(SAMPLE, limit=1)
    assert list(data) == ['1.2.0']


def test_inline_markdown_rendering():
    entry = parse_changelog(SAMPLE)['1.2.0']['added'][0]
    assert '<strong>New thing.</strong>' in entry['raw']
    assert '<a href="https://example.com/a">link</a>' in entry['raw']
    assert '<code>code</code>' in entry['raw']
    assert entry['title'] == ''  # no 'title: content' separator in this entry
    assert entry['raw'].startswith('<li>')


def test_html_is_escaped():
    entry = parse_changelog(SAMPLE)['1.2.0']['fixed'][0]
    # Literal angle brackets from the source must be escaped, never raw HTML.
    assert '<script>' not in entry['raw']
    assert '&lt;script&gt;' in entry['raw']
    assert '1 &lt; 2' in entry['raw']


def test_empty_changelog():
    assert parse_changelog('') == {}
