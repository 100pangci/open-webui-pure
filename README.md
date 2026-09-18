# Open WebUI

Open WebUI is a self-hosted, lightweight chat interface for OpenAI-compatible
APIs. It provides authenticated conversations, streaming responses, model
selection, local image attachments, and image generation and editing through
the configured OpenAI-compatible provider.

## Features

- OpenAI-compatible chat and image APIs
- User authentication, sessions, roles, and user management
- Streaming chat responses over Socket.IO
- Multiple configured models and per-model system prompts and parameters
- Image generation and image editing
- Local image uploads stored in the application data directory
- SQLite by default; PostgreSQL, Redis, Azure/Entra ID and LDAP are opt-in
- Responsive desktop and mobile interface
- Multilingual interface

## Optional features

The default install and the default container image ship **SQLite only** and
are tuned for personal, home and small deployments: no PostgreSQL driver, no
Redis client, no Azure SDK and no LDAP client are installed or imported.

Enable a feature only when it is actually used:

| Feature | pip extra | requirements file | container build arg |
| --- | --- | --- | --- |
| PostgreSQL (Psycopg 3) | `open-webui[postgres]` | `backend/requirements-postgres.txt` | `ENABLE_POSTGRES=true` |
| Redis (multi-instance) | `open-webui[redis]` | `backend/requirements-redis.txt` | `ENABLE_REDIS=true` |
| Azure / Entra ID auth | `open-webui[azure]` | `backend/requirements-azure.txt` | `ENABLE_AZURE=true` |
| LDAP authentication | `open-webui[ldap]` | `backend/requirements-ldap.txt` | `ENABLE_LDAP=true` |
| Backend PDF export | `open-webui[pdf]` | `backend/requirements-pdf.txt` | `ENABLE_PDF=true` |
| Admin code formatting | `open-webui[code-format]` | `backend/requirements-code-format.txt` | `ENABLE_CODE_FORMAT=true` |
| Pillow image-edit normalization | `open-webui[pillow]` | `backend/requirements-pillow.txt` | `ENABLE_PILLOW=true` |
| `open-webui` CLI (typer) | `open-webui[cli]` | `backend/requirements-cli.txt` | — |

> The default UI renders PDF exports client-side (jsPDF + html2canvas). The
> backend PDF endpoint is only a fallback and stays disabled unless
> `ENABLE_PDF=true` is set. Code formatting and Pillow normalization degrade
> gracefully when their extras are absent.

> The `open-webui serve` CLI is optional even for native installs; the container
> starts uvicorn directly (`backend/start.sh`) and does not need typer/rich.

Native install example:

```bash
pip install -r backend/requirements-min.txt -r backend/requirements-postgres.txt
# or: pip install "open-webui[postgres,redis]"
```

Container build example:

```bash
podman build \
  --build-arg ENABLE_POSTGRES=true \
  --build-arg ENABLE_REDIS=true \
  -t localhost/open-webui:full .

# or via compose environment variables (see podman-compose.yaml):
WEBUI_ENABLE_POSTGRES=true WEBUI_ENABLE_REDIS=true \
  podman compose -f podman-compose.yaml up -d --build
```

The same applies to compose: `podman-compose.yaml` forwards
`WEBUI_ENABLE_POSTGRES`, `WEBUI_ENABLE_REDIS`, `WEBUI_ENABLE_AZURE`,
`WEBUI_ENABLE_LDAP`, `WEBUI_ENABLE_PDF`, `WEBUI_ENABLE_CODE_FORMAT` and
`WEBUI_ENABLE_PILLOW` (all default to `false`). The default image tag is
`localhost/open-webui:pure`.

PostgreSQL support uses **Psycopg 3 exclusively** (`postgresql+psycopg://`);
psycopg2 is not required. Migrations and existing SQLite data are untouched —
the optional split only changes which driver packages are installed.

## Installation

Use Python 3.11 or 3.12 for a native installation. The `open-webui` CLI is an
opt-in extra; without it, run the server with uvicorn:

```bash
# with the CLI
pip install "open-webui[cli]"
open-webui serve

# or without the CLI (lighter)
pip install open-webui
python -m uvicorn open_webui.main:app --host 0.0.0.0 --port 8080
```

The server listens on `http://localhost:8080` by default.

## Podman

Build and start the application with the included CPU-only compose file:

```bash
podman compose -f podman-compose.yaml up -d --build
```

The application is available at `http://localhost:3000`. The compose file
preserves the existing `open-webui` volume at `/app/backend/data`; do not use
volume-removal flags when stopping the service if database and uploaded images
must be retained.

Set the provider before starting the service, for example:

```bash
export OPENAI_API_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=your_secret_key
podman compose -f podman-compose.yaml up -d --build
```

Useful commands:

```bash
make startAndBuild
make logs
make health
make stop
```

## Development

Install frontend dependencies and run the development server:

```bash
npm ci
npm run dev
```

Run frontend checks and tests:

```bash
npm run check
npm run test:frontend
npm run build
```

## License

This project contains code under multiple licenses. The current codebase
includes components licensed under the Open WebUI License with an additional
requirement to preserve the "Open WebUI" branding, as well as prior
contributions under their respective original licenses. For a detailed record
of license changes and the applicable terms for each section of the code, see
[`LICENSE_HISTORY`](./LICENSE_HISTORY). For complete licensing details, see
[`LICENSE`](./LICENSE) and [`LICENSE_HISTORY`](./LICENSE_HISTORY).

## Support

Open an issue or join the [Open WebUI Discord community](https://discord.gg/5rJgQTnV4s)
for questions and support.

## Security

Report security vulnerabilities through the [responsible disclosure program on
GitHub](https://github.com/open-webui/open-webui/security). Do not disclose
security issues publicly before they have been reviewed.
