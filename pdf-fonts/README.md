# PDF export fonts

These fonts are used **only** by the optional backend PDF export
(`backend/open_webui/utils/pdf_generator.py`, enabled with
`ENABLE_PDF=true` / `pip install "open-webui[pdf]"`):

| File | Use |
| --- | --- |
| `NotoSans-Regular.ttf` / `-Bold` / `-Italic` | PDF body text |
| `NotoSansSC-Regular.ttf` | CJK fallback (Simplified Chinese) |
| `NotoSansKR-Regular.ttf` | CJK fallback (Korean) |
| `NotoSansJP-Regular.ttf` | CJK fallback (Japanese) |
| `Twemoji.ttf` | Emoji fallback |

The `*-Variable.ttf` files are kept for reference only; the PDF generator
loads static fonts and never reads them.

The frontend uses its own web fonts from `static/assets/fonts/` (Inter,
Vazirmatn, emoji sprite sheets) and does not read this directory.

The default container image does **not** include these files (~25 MB); the
Dockerfile copies the seven runtime fonts into
`/app/backend/open_webui/static/fonts/` only when `ENABLE_PDF=true`.
Running from a source checkout, `open_webui.env` falls back to this directory
when no fonts are installed at the default location, so the PDF endpoint keeps
working locally with the `pdf` extra.
