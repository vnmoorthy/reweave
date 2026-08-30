# Deploying Reweave with Docker

The repo ships a multi-stage `Dockerfile` (builder + `python:3.12-slim` runtime,
non-root user) and a `compose.yaml`. The image runs `reweave serve --host 0.0.0.0`
on port 8321, stores its SQLite registry at `/data/reweave.db`, and has a
`HEALTHCHECK` against `GET /api/health`.

## docker run

```sh
docker build -t reweave .
docker run -d --name reweave -p 8321:8321 -v reweave-data:/data reweave
```

Dashboard: <http://localhost:8321/> — health: `curl http://localhost:8321/api/health`.

With Bright Data fetching and API auth:

```sh
docker run -d --name reweave -p 8321:8321 -v reweave-data:/data \
  -e BRIGHTDATA_API_KEY -e BRIGHTDATA_ZONE -e REWEAVE_API_TOKEN reweave
```

## docker compose

```sh
docker compose up -d --build
```

`compose.yaml` defines one service on port 8321 with a named volume
(`reweave-data`) mounted at `/data` and `restart: unless-stopped`. It passes
`BRIGHTDATA_API_KEY`, `BRIGHTDATA_ZONE`, `REWEAVE_WATCH_INTERVAL`, and
`REWEAVE_API_TOKEN` through from your shell (or a `.env` file next to
`compose.yaml`) only when they are set.

## Environment variables

| Variable | Default in image | Purpose |
| --- | --- | --- |
| `REWEAVE_DB` | `/data/reweave.db` | SQLite registry path. Keep it on the volume so state survives container replacement. |
| `REWEAVE_API_TOKEN` | unset | When set, mutating/API routes require `Authorization: Bearer <token>`; `/`, `/demo-site`, `/api/health`, and `/metrics` stay open. |
| `REWEAVE_AUTOPILOT` | `1` (set by `serve`) | Continuous background monitoring. Start with `--no-autopilot` to disable. |
| `REWEAVE_WATCH_INTERVAL` | `60` seconds (code default) | Autopilot poll interval; floor of 5s. |
| `BRIGHTDATA_API_KEY` | unset | Enables Bright Data Web Unlocker for `http(s)://` sources. Without it, remote fetches fall back to plain httpx. |
| `BRIGHTDATA_ZONE` | `web_unlocker1` (code default) | Bright Data zone name. |
| `REWEAVE_DEMO_DIR` | unset (uses bundled `/app/demo`) | Override the demo storefront directory. |

## Volume and backup

All persistent state — sources, spec versions, runs, events, heals, demo
variant — is the single SQLite file `/data/reweave.db`. To back it up without
stopping the container, use SQLite's online backup rather than copying the
live file:

```sh
docker exec reweave python -c "import sqlite3; sqlite3.connect('/data/reweave.db').backup(sqlite3.connect('/data/backup.db'))"
docker cp reweave:/data/backup.db ./reweave-backup.db
```

Restore by placing the file back at `/data/reweave.db` while the container is
stopped. Deleting the `reweave-data` volume resets Reweave completely.

## Reverse proxy

The container speaks plain HTTP. For anything beyond localhost, put it behind
a TLS-terminating proxy and set `REWEAVE_API_TOKEN` — without a token every
API route, including approve/rollback, is unauthenticated. Example (Caddy):

```
reweave.example.com {
    reverse_proxy 127.0.0.1:8321
}
```

Bind the published port to loopback so only the proxy reaches it:
`-p 127.0.0.1:8321:8321` (or `"127.0.0.1:8321:8321"` in `compose.yaml`).
