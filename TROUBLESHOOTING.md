# Open WebUI Pure Troubleshooting

Short list of the failures that actually happen with this fork. This is not
the upstream Open WebUI troubleshooting guide: Ollama, RAG, web search, tools
and audio do not exist here.

## The container starts but the model list is empty

1. Check the provider URL from inside the container — `localhost` there is the
   container, not your machine:

   ```bash
   podman exec -it open-webui curl -sS http://<provider-host>:<port>/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```

2. For a provider running on the host, use `host.containers.internal` or the
   host LAN IP (for example `http://192.168.1.20:8000/v1`), not `127.0.0.1`.
3. Verify `OPENAI_API_BASE_URL` / `OPENAI_API_KEY` (or the connection in
   **Admin Settings → Connections**) and that the URL ends with `/v1` when the
   server expects it.

## The container cannot reach the internet (provider, OAuth, avatars)

Set proxy variables before starting:

```bash
export HTTPS_PROXY=http://host.containers.internal:3128
./podman.sh update
```

- `127.0.0.1` inside the container is the container itself.
- `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and `NO_PROXY` are forwarded to the
  container by `docker-compose.yml`; nothing is auto-detected.
- Some providers are reachable directly — leave the variables unset if so.

## A feature returns 501 / "not available"

Most optional features are compiled into the image at build time or installed
as extras, and are absent by default:

| Feature                       | Enable with                                                                |
| ----------------------------- | -------------------------------------------------------------------------- |
| PostgreSQL                    | `WEBUI_ENABLE_POSTGRES=true` or `pip install "open-webui[postgres]"`       |
| Redis                         | `WEBUI_ENABLE_REDIS=true` or `pip install "open-webui[redis]"`             |
| Azure OpenAI / Entra ID token | `WEBUI_ENABLE_AZURE=true` or `pip install "open-webui[azure]"`             |
| LDAP                          | `WEBUI_ENABLE_LDAP=true` or `pip install "open-webui[ldap]"`               |
| Backend PDF export            | `WEBUI_ENABLE_PDF=true` or `pip install "open-webui[pdf]"`                 |
| Admin code formatting         | `WEBUI_ENABLE_CODE_FORMAT=true` or `pip install "open-webui[code-format]"` |
| Pillow image normalization    | `WEBUI_ENABLE_PILLOW=true` or `pip install "open-webui[pillow]"`           |

Rebuild after changing a build arg: `./podman.sh update`.

## Data disappeared after an update

The data lives in the Podman volume attached to `/app/backend/data`. It is
preserved by `./podman.sh down` and `./podman.sh update`; only explicit volume
removal (`podman volume rm open-webui_open-webui`) deletes it. Never delete the
volume to "fix" a container problem.

## Sessions are lost after every rebuild

The JWT signing key must live inside the volume. `docker-compose.yml` sets
`WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key`; keep that setting
(or set a fixed `WEBUI_SECRET_KEY`) if you write your own compose file.

## The container keeps running the old image after `podman compose build`

This is a compose quirk: an unchanged compose config does not recreate the
container when only the image ID changed. Use:

```bash
./podman.sh update
```

It rebuilds and recreates the container when the image differs. `podman.sh up`
does the same check before starting.

## SQLite: slow browsing with a very large database

The defaults (16 MiB page cache, 64 MiB mmap) are tuned for personal and small
deployments. Raise them for large databases:

```bash
DATABASE_SQLITE_PRAGMA_CACHE_SIZE=-65536   # KiB (SQLite convention)
DATABASE_SQLITE_PRAGMA_MMAP_SIZE=268435456
```

## Where logs are

```bash
./podman.sh logs                    # container logs
journalctl -t open-webui            # only if you run it under systemd
```

For upstream Open WebUI issues unrelated to this fork, see
<https://github.com/open-webui/open-webui>.
