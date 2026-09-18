# Open WebUI Pure — Handoff

Everything a maintainer needs in five minutes. Round-by-round construction
logs live in git history, not here.

## Product boundary

Open WebUI Pure is an unofficial, aggressively subtractive fork of upstream
Open WebUI (baseline **v0.11.3**). The goal is not to reimplement Open WebUI:
it is to keep the mature chat core and the original branding while physically
removing the features, dependencies and background costs that personal / home
/ small multi-user deployments do not need.

- OpenAI-compatible first: configured `OPENAI_API_BASE_URL`/`OPENAI_API_KEY`
  endpoints, no Ollama-specific stack.
- SQLite-first: PostgreSQL, Redis, Azure/Entra ID, LDAP, PDF and other extras
  are opt-in and absent from the default install and image.
- One Python process; Socket.IO for streaming; no background workers.
- **Any change must answer: does Pure need this?** If it cannot be proven
  needed, delete it. Do not re-add removed features, dependencies,
  configuration entries or compatibility shims.
- Must never be deleted: `LICENSE`, `LICENSE_HISTORY`, `LICENSE_NOTICE`,
  Open WebUI branding, historical Alembic migrations, the current backend
  test suite, data-compatibility logic, SSRF/security hardening, SQLite and
  the optional PostgreSQL/Redis/Azure/LDAP paths, and the Docker/Podman
  runtime path.

## Retained features

- Authentication, sessions, roles, user management, groups
- Folders, sharing, per-model access control
- Chat: streaming and non-streaming, model selection, per-model system
  prompts and parameters, chat history, temporary chats
- Files and images; image uploads stored in the data directory
- OpenAI-compatible chat completions plus image generation/editing
- Workspace models and prompts, playground (completions/images)
- Settings, admin connections, changelog, PWA manifest, i18n
- Optional (opt-in): PostgreSQL (Psycopg 3), Redis, Azure/Entra ID, LDAP,
  backend PDF export, admin code formatting, Pillow normalization, CLI
- Security/engineering: SSRF-hardened outbound fetches, local Brotli+gzip
  middleware, benchmarked SQLite pragmas, lazy imports

## Removed (do not re-import)

Ollama integration; RAG, vector databases, knowledge bases, embeddings; web
search; tools, MCP, functions, skills, pipelines; terminal / code
interpreter; audio (STT/TTS/voice); channels, notes, calendar, automations;
evaluations, arena, feedback; memory; notifications, webhooks, telemetry
(OpenTelemetry, SCIM); cloud storage (Google Drive, OneDrive); ComfyUI,
AUTOMATIC1111 and Gemini image backends.

## Footprint

Measured on the maintainer machine (rootless Podman, fresh data volume, empty
configuration, one OpenAI-compatible provider), 2026-09-18:

| Metric                                | Value                       |
| ------------------------------------- | --------------------------- |
| Image size                            | ~300 MB                     |
| Fresh idle (cgroup)                   | ~101–103 MB                 |
| Fresh idle (RSS / PSS)                | ~120 MB / 105–115 MB        |
| Fresh idle (Private_Dirty)            | ~93 MB                      |
| Startup to `/health`                  | ~1.6 s                      |
| After real use (login, chats, images) | ~113 MB stats / ~133 MB RSS |

Deliberate choices behind the numbers:

- `PYTHONDONTWRITEBYTECODE=1` is set **after** the `pip install` layer in the
  Dockerfile. Moving it earlier also suppresses build-time stdlib `.pyc`
  (~5.5 MB smaller image) but costs ~0.2–0.3 s on every start; do not move it.
- Build-time `.pyc` for site-packages (~25 MB) is intentionally kept; deleting
  it costs ~1 s per start.
- `uvloop` (~13 MB), Socket.IO (~12 MB) and the slim base image are kept;
  further slimming requires performance, architecture or compatibility
  trade-offs and is out of scope.
- PDF fonts live in `pdf-fonts/` and enter the image only with
  `ENABLE_PDF=true`; the four unused `*-Variable.ttf` files were deleted.

## Optional dependencies

| Feature                | pip extra                 | requirements                           | build arg            |
| ---------------------- | ------------------------- | -------------------------------------- | -------------------- |
| PostgreSQL (Psycopg 3) | `open-webui[postgres]`    | `backend/requirements-postgres.txt`    | `ENABLE_POSTGRES`    |
| Redis                  | `open-webui[redis]`       | `backend/requirements-redis.txt`       | `ENABLE_REDIS`       |
| Azure / Entra ID       | `open-webui[azure]`       | `backend/requirements-azure.txt`       | `ENABLE_AZURE`       |
| LDAP                   | `open-webui[ldap]`        | `backend/requirements-ldap.txt`        | `ENABLE_LDAP`        |
| Backend PDF export     | `open-webui[pdf]`         | `backend/requirements-pdf.txt`         | `ENABLE_PDF`         |
| Code formatting        | `open-webui[code-format]` | `backend/requirements-code-format.txt` | `ENABLE_CODE_FORMAT` |
| Pillow normalization   | `open-webui[pillow]`      | `backend/requirements-pillow.txt`      | `ENABLE_PILLOW`      |
| CLI (typer)            | `open-webui[cli]`         | `backend/requirements-cli.txt`         | —                    |

`backend/requirements-min.txt` is the only file installed by the default
image. `backend/requirements-optional.txt` aggregates the rest.

## Tests and verification

```bash
# backend: 100 tests (SSRF hardening, compression q-value negotiation,
# changelog parsing)
PYTHONPATH=backend pytest backend/open_webui/test -q

# frontend
npm run test:frontend
npm run build

# container build and runtime
./podman.sh build
./podman.sh update
curl --fail http://localhost:3000/health
```

Before shipping a change, check the retained flows: login, two-user
isolation, chat (streaming and non-streaming), stop generation, file upload,
image upload, image generation/editing, and the OpenAI-compatible connection.
After a dependency or Dockerfile change, run `pip check` inside the image
(the Dockerfile does it at build time and fails the build on broken deps).

## Upstream sync principles

1. Cherry-pick upstream security and bug fixes; do not merge whole branches.
2. When a fix touches a removed feature, adapt only the part that affects a
   retained feature.
3. Never import a module, dependency or config entry whose feature is under
   "Removed". Keep lazy imports lazy.
4. Do not touch `backend/open_webui/migrations/` (58 historical revisions;
   Alembic head `d4c1a8e37b62`).
5. Re-run the test commands above; keep `npm run build` and the container
   regression green.

## Data and volumes — hard rules

- Data lives in the Podman volume `open-webui_open-webui`, mounted at
  `/app/backend/data` (SQLite database, uploads, secret key).
- Never delete the volume. Never run `podman compose down -v` or
  `podman volume rm` to "fix" a container problem.
- `WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key` must stay in
  `docker-compose.yml`; otherwise every container recreation regenerates the
  JWT key and invalidates all sessions (401s everywhere).
- `podman.sh down`/`update` remove the container only, never the volume.
- Historical migrations and existing SQLite data must keep working; verify
  with a copy of a real volume before publishing a change that touches
  `config.py`, `internal/db.py` or migrations.

## Known design trade-offs and traps

- **Compose does not recreate on image change.** `podman compose up -d` keeps
  the old container when only the image ID changed; `./podman.sh update`
  detects the ID change and uses `--force-recreate`.
- **`static/static/` is required.** On startup `config.py` clears the top
  level of `backend/open_webui/static/` and copies it back from the frontend
  build (`build/static`). Running `open_webui.main` from source without a
  fresh `npm run build` deletes those files and breaks
  `/static/logo.png`, favicons and splash images. Build the frontend first.
- **Image endpoints use their own base URL.** `OPENAI_API_BASE_URL` is forced
  to `https://api.openai.com/v1` at the end of `config.py`; image generation
  and editing need `IMAGES_OPENAI_API_BASE_URL`/`IMAGES_OPENAI_API_KEY` or an
  admin-configured connection.
- **CHANGELOG has two paths.** The runtime reads the build-time
  `latest-changelog.json`; `CHANGELOG.md` stays in the image as a fallback.
- **SSRF hardening is mandatory** for outbound image/avatar fetches
  (`backend/open_webui/utils/ssrf.py`); do not replace it with plain
  `aiohttp`/`requests` calls.
- **Swagger UI is kept** for `ENV=dev` `/docs`; it is not served in `prod`.
- **The update check follows the fork.** `/api/version/updates` reads the
  newest semver tag from `WEBUI_UPDATE_CHECK_REPO` (default
  `100pangci/open-webui-pure`) instead of upstream GitHub releases. When
  syncing an upstream version, tag the repository (`v*`); the same tag also
  triggers the Docker Hub image publish.
- Container-to-host networking: `127.0.0.1` inside the container is the
  container itself. Use `host.containers.internal` or the host LAN IP for
  providers/proxies running on the host.

## Repository layout

- `Dockerfile` — multi-stage (frontend / changelog / pdf-fonts / runtime),
  `ENABLE_*` build args, build-time `pip check`, runtime bytecode off.
- `podman.sh` + `docker-compose.yml` — the single supported container entry
  point; generic proxy pass-through, persistent volume, recreate-on-change.
- `backend/open_webui/` — application; `test/` holds the 100 tests;
  `migrations/` is append-only history.
- `src/` — SvelteKit frontend; `static/` — SPA assets (branding notices in
  `static/BRANDING.md`).
- `.github/workflows/` — three Pure workflows: backend CI (Ruff + tests),
  frontend CI (format + i18n + build + tests), image publish (test +
  amd64/arm64 to Docker Hub, `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`
  secrets, tags and manual dispatch only).
- `.env.example` — the supported configuration surface.
