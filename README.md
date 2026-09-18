# Open WebUI Pure

Open WebUI Pure is an **unofficial, lightweight fork of
[Open WebUI](https://github.com/open-webui/open-webui)**. It does not try to
reimplement Open WebUI: it keeps the mature chat core and the original Open
WebUI branding, and physically removes the features, dependencies and
background costs that a personal or small self-hosted deployment does not
need.

The result is one small image, one Python process, SQLite by default, and an
OpenAI-compatible API surface. It is **not** a drop-in replacement for full
Open WebUI.

- **OpenAI-compatible first** — one or more `OPENAI_API_BASE_URL` /
  `OPENAI_API_KEY` endpoints; no Ollama-specific stack.
- **SQLite-first** — PostgreSQL, Redis, Azure/Entra ID, LDAP and PDF export
  are opt-in extras, absent from the default install and image.
- **Personal / home / small deployment** — tuned for a handful of users on
  modest hardware; still multi-user with roles, groups and sharing.
- **~300 MB image**, **~100 MB fresh idle cgroup**, **~1.6 s startup** on a
  fresh data volume (see [Footprint](#footprint)).
- **Upstream-derived, aggressively subtractive** — based on Open WebUI
  v0.11.3, with every removal recorded in [`HANDOFF.md`](./HANDOFF.md).

## Footprint

Measured with rootless Podman and a fresh data volume (empty configuration,
one OpenAI-compatible provider configured):

| Metric                                | Value                      |
| ------------------------------------- | -------------------------- |
| Image size                            | **~300 MB**                |
| Fresh idle (cgroup)                   | **~101–103 MB**            |
| Fresh idle (RSS / Private_Dirty)      | ~120 MB / **~93 MB**       |
| Startup to `/health`                  | **~1.6 s**                 |
| After real use (login, chats, images) | ~113 MB stats, ~133 MB RSS |

The footprint comes from deliberate engineering, not feature loss: lazy
imports, build-time changelog JSON, a local Brotli/gzip middleware (no
`zstandard`), benchmarked SQLite pragmas, PDF-only fonts, and SSRF-hardened
outbound fetches with no extra runtime dependency.

## Features

- OpenAI-compatible chat completions (streaming and non-streaming)
- OpenAI-compatible image generation and editing, plus local image uploads
- Authentication, sessions, roles, user management
- Groups, folders, sharing and per-model access control
- Workspace models and prompts, per-model system prompts and parameters
- Playground (chat completions and images), settings and admin connections
- Changelog, PWA manifest, multilingual interface, responsive layout

## Removed

The following are intentionally **not** part of Pure and must not be added
back:

- Ollama-specific integration
- RAG, vector databases, knowledge bases, file embeddings
- Web search
- Tools, MCP, functions, skills, pipelines
- Terminal / code interpreter
- Audio: STT, TTS, voice calls
- Channels, notes, calendar, automations
- Evaluations, arena, feedback
- Memory, notifications, webhooks, telemetry (OpenTelemetry, SCIM)
- Cloud storage (Google Drive, OneDrive)
- ComfyUI / AUTOMATIC1111 / Gemini image backends

If you need any of these, use upstream
[Open WebUI](https://github.com/open-webui/open-webui).

## Optional features

The default image and default install ship **SQLite only**. Enable extras only
when they are actually used:

| Feature                            | pip extra                 | requirements file                      | container build arg       |
| ---------------------------------- | ------------------------- | -------------------------------------- | ------------------------- |
| PostgreSQL (Psycopg 3)             | `open-webui[postgres]`    | `backend/requirements-postgres.txt`    | `ENABLE_POSTGRES=true`    |
| Redis (multi-instance)             | `open-webui[redis]`       | `backend/requirements-redis.txt`       | `ENABLE_REDIS=true`       |
| Azure OpenAI / Entra ID token auth | `open-webui[azure]`       | `backend/requirements-azure.txt`       | `ENABLE_AZURE=true`       |
| LDAP authentication                | `open-webui[ldap]`        | `backend/requirements-ldap.txt`        | `ENABLE_LDAP=true`        |
| Backend PDF export                 | `open-webui[pdf]`         | `backend/requirements-pdf.txt`         | `ENABLE_PDF=true`         |
| Admin code formatting              | `open-webui[code-format]` | `backend/requirements-code-format.txt` | `ENABLE_CODE_FORMAT=true` |
| Pillow image-edit normalization    | `open-webui[pillow]`      | `backend/requirements-pillow.txt`      | `ENABLE_PILLOW=true`      |
| `open-webui` CLI (typer)           | `open-webui[cli]`         | `backend/requirements-cli.txt`         | —                         |

The UI renders PDF exports client-side (jsPDF + html2canvas). The backend PDF
endpoint is only a fallback and stays disabled unless `ENABLE_PDF=true`.
PostgreSQL support uses **Psycopg 3 exclusively** (`postgresql+psycopg://`).

## Installation

### Podman (recommended)

```bash
git clone https://github.com/100pangci/open-webui-pure.git
cd open-webui-pure
export OPENAI_API_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=your_key
./podman.sh up
```

The application is served at `http://localhost:3000`. The single entry point
`./podman.sh` supports `up`, `build`, `update`, `restart`, `stop`, `down`,
`logs`, `health` and `shell`; `update` rebuilds and reliably switches the
container to the new image. The data volume (`open-webui_open-webui`) is never
removed by the script.

Enable optional dependencies at build time:

```bash
WEBUI_ENABLE_POSTGRES=true WEBUI_ENABLE_REDIS=true ./podman.sh update
```

Prebuilt multi-arch images are published to
`ghcr.io/100pangci/open-webui-pure` on version tags.

### From source

Python 3.11 or 3.12. Do **not** `pip install open-webui` — that installs the
official PyPI package, not this fork.

```bash
git clone https://github.com/100pangci/open-webui-pure.git
cd open-webui-pure
pip install .                    # builds the frontend locally (needs Node.js)
python -m uvicorn open_webui.main:app --host 0.0.0.0 --port 8080
```

With optional extras:

```bash
pip install ".[postgres]"
pip install ".[redis]"
pip install ".[cli]"             # then: open-webui serve
```

Set configuration through environment variables; see
[`.env.example`](./.env.example) for the supported set (provider, secret key,
port/host, SQLite tuning, PostgreSQL, Redis, OAuth/LDAP, proxy, TLS).

### Development

```bash
npm ci
npm run dev        # Vite dev server, proxies /api and /openai to :8080
```

## Tests

```bash
# backend (100 tests: SSRF, compression negotiation, changelog)
PYTHONPATH=backend pytest backend/open_webui/test -q

# frontend
npm run test:frontend
npm run build
```

CI runs exactly these checks on `main`.

## Upstream sync

Pure is based on upstream Open WebUI v0.11.3. Security fixes and bug fixes
from upstream are welcome, but every sync must keep the subtraction intact:
do not import a module, dependency or configuration entry whose feature is
listed under [Removed](#removed). See [`HANDOFF.md`](./HANDOFF.md) for the
product boundary, footprint history and the data/volume rules.

## License and branding

This project contains code under multiple licenses, including the Open WebUI
License, which requires preserving the "Open WebUI" branding. See
[`LICENSE`](./LICENSE), [`LICENSE_HISTORY`](./LICENSE_HISTORY) and
[`LICENSE_NOTICE`](./LICENSE_NOTICE). The Open WebUI name, logo and visual
identifiers in this repository are covered by those terms and must not be
altered or removed beyond what the license permits.

## Support

This repository is an unofficial, trimmed fork maintained on a best-effort
basis. Issues and Discussions are disabled; the only contribution channel is a
pull request.

- For problems caused by the trimming (removed features, optional
  dependencies, Pure-specific packaging), open a pull request or leave
  feedback on the relevant commit.
- For upstream Open WebUI bugs and general product questions, use the
  upstream project: <https://github.com/open-webui/open-webui>. Do not present
  a Pure problem as an upstream issue.
- Security: Pure inherits upstream's security model and fixes. Report
  vulnerabilities in inherited code through upstream's
  [security advisories](https://github.com/open-webui/open-webui/security);
  report Pure-specific packaging/configuration issues in this repository.
