# Deployment

| Mode | Command | Live simulation | State changes | Intended for |
|---|---|---|---|---|
| Docker Compose (default) | `docker compose up --build` | yes | yes (local) | local use, demos on your machine |
| Docker demo overlay | `docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build` | yes, scripted storyline | **no** (read-only) | unattended / public demonstrations |
| Local development | `uvicorn …` + `npm run dev` | yes | yes | development |
| Single process | `npm run build`, then backend with `OTST_FRONTEND_DIST=../frontend/dist` | yes | yes | quick local use without nginx |
| Static GitHub Pages | — | — | — | **not implemented** in v0.1.0 (a prerecorded playback build is on the roadmap) |

A static recording is never presented as a live backend: the UI shows connection state, `RUNNING/PAUSED`, `DEMO` and
`READ-ONLY` badges from the backend itself.

## Docker Compose

* `backend` (FastAPI, Python 3.12-slim, user `otst` uid 10001) — port `127.0.0.1:${OTST_API_PORT:-8000}`,
  healthcheck on `/api/health`, SQLite on the `otst-data` volume, reference evaluation results baked into the image.
* `frontend` (nginx-unprivileged) — port `127.0.0.1:${OTST_WEB_PORT:-8080}`, serves the SPA, proxies `/api` and `/ws`
  to the backend (same origin for the browser), sets CSP and security headers; healthcheck on `/`.
* Both containers: read-only root filesystem, tmpfs `/tmp`, `cap_drop: ALL`, `no-new-privileges`, memory/CPU limits.
* Ports bind to localhost only. Change host ports with `OTST_WEB_PORT` / `OTST_API_PORT`
  (CORS origins follow `OTST_WEB_PORT` automatically).

```bash
docker compose up --build -d
docker compose ps                    # both services should be "healthy"
curl http://127.0.0.1:8080/api/health
docker compose down -v               # stop and delete the data volume
```

## Configuration (environment)

See [`.env.example`](../.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `OTST_DATABASE_URL` | `sqlite:///./data/ot_sentinel.db` | SQLAlchemy URL |
| `OTST_CORS_ORIGINS` | localhost dev/preview/compose origins | allowed browser origins (CORS + WebSocket) |
| `OTST_AUTOSTART` | `true` | start the simulation on boot |
| `OTST_DEMO_MODE` | `false` | scripted scenario storyline on a loop |
| `OTST_READ_ONLY` | `false` | refuse all state-changing API calls |
| `OTST_API_TOKEN` | empty | require `X-API-Key` for state-changing calls |
| `OTST_MAX_SPEED` | `10` | maximum simulation speed |
| `OTST_RATE_LIMIT_PER_MINUTE` | `240` | state-changing requests per client per minute |
| `OTST_MAX_BODY_BYTES` | `65536` | request body limit |
| `OTST_RETENTION_RUNS` | `12` | number of recorded runs kept |
| `OTST_MAX_SAMPLES_PER_RUN` | `60000` | per-run sample cap (≈ 8.3 h at 2 Hz) |
| `OTST_WS_MAX_CLIENTS` | `25` | concurrent WebSocket clients |
| `OTST_FRONTEND_DIST` | empty | serve a built frontend from the backend |
| `OTST_REFERENCE_EVALUATION` | empty (set in the image) | evaluation JSON shown until a new run exists |

## Public demonstration checklist

1. Use the demo overlay (`OTST_READ_ONLY=true`, `OTST_DEMO_MODE=true`, `OTST_MAX_SPEED=1`).
2. Put a TLS-terminating reverse proxy in front of the `frontend` container; do not expose port 8000.
3. Add the public origin to `OTST_CORS_ORIGINS` only if the API is accessed cross-origin (not needed behind nginx).
4. Keep container limits; there is exactly one simulation per backend process and no endpoint can create more.
5. Remember there is no user authentication or RBAC in v0.1.0.

## CI

`.github/workflows/ci.yml` (on pull requests and pushes to `main`, `contents: read` only, actions pinned to commit
SHAs, `persist-credentials: false`): backend lint/format/mypy/pytest + single-seed evaluation gate, frontend
lint/typecheck/tests/build, Playwright end-to-end, `pip-audit` and `npm audit`, Docker Compose build and health check.
`codeql.yml` runs CodeQL for Python and TypeScript. Dependabot updates pip, npm, GitHub Actions and Docker base images
weekly.
