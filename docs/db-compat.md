# Database compatibility

Open WebUI Pure keeps the upstream application schema and Alembic migration
history, but it **freezes that history**: `backend/open_webui/migrations/` is
append-only and Pure never imports upstream migration files. Pure's Alembic
head is `d4c1a8e37b62`.

## Supported databases

Pure starts only when the database's `alembic_version.version_num` is one of
Pure's own revisions (any revision reachable from `d4c1a8e37b62`), or when the
database is fresh (no `alembic_version` table).

At startup, `config.py` reads the current revision before running
`alembic upgrade head`:

- **Fresh database** — migrations run and create the schema at `d4c1a8e37b62`.
- **Pure database** — migrations run normally (usually a no-op at head).
- **Database migrated by a different Open WebUI release** — if the recorded
  revision is not in Pure's migration history, startup fails with a readable
  error and **no migration is attempted**. Examples include upstream
  v0.12.5 (`0bd252b206fb`) and v0.13.0 (`e42c8f710a36`).

The guard exists because upstream and Pure migration histories diverged while
both continued to use the same `alembic_version` table. Running Pure's
migrations on a database stamped by another release can corrupt the schema or
silently skip columns that Pure expects.

## Recovering a database migrated by upstream Open WebUI

Keep a backup taken **before** the upstream migration. Then choose one path:

1. **Restore the pre-upstream backup.** Point `DATABASE_URL` at the restored
   file (or restore it into the volume) and start Pure.
2. **Export and re-import.** Start the upstream-migrated database with the
   matching upstream release, export the data you need (chats, users, files),
   and import it into a fresh Pure database using the API or SQL. Do not copy
   upstream's `alembic_version` row into the Pure database.

Do **not** run `alembic stamp`, `alembic downgrade`, or edit
`alembic_version` / table definitions by hand on a production database. Those
operations make the failure silent instead of readable.

## Notes

- `ENABLE_DB_MIGRATIONS=false` disables the startup upgrade; the compatibility
  check does not run in that mode, so the operator owns schema validation.
- The check reads only `alembic_version`; it does not inspect or modify any
  other table.
- Back up the SQLite file (and uploads / `.webui_secret_key`) before any
  upgrade. See [`HANDOFF.md`](../HANDOFF.md) for the volume rules.