# Initial Implementation Contract (BINDING)

This document pins every cross-service interface for the initial skeleton.
Builders implement AGAINST this contract; do not renegotiate it unilaterally.
Full requirements: `init.md` (spec), `DESIGN.md` (UI system), `personal_investment_dashboard_architecture.md` (context), `CLAUDE.md` (coding rules).

## 0. Scope decisions (deviations from init.md, already decided)

- **Kiwoom API (init.md §2-11) is DEFERRED.** It conflicts with §18 (실제 증권사 API 금지) and Kiwoom OpenAPI+ is Windows-only COM (cannot run in Linux containers). Documented in README as next-phase work (Kiwoom REST API recommended).
- **Added endpoint** `GET /api/v1/jobs/stats` — required by the Overview screen (§10 counts).
- **alembic.ini lives at repo root**, migrations in `database/migrations/` (honors §5 folder layout; runnable from container WORKDIR /app and from repo root).
- **Tailwind v3.4** (not v4), **no Radix**; shadcn-style components are hand-vendored.
- Status palette: DESIGN.md has no error color → pin semantic colors (see §8).

## 1. Services & topology (docker-compose)

| service  | image/build | external port | internal DNS |
|---|---|---|---|
| web      | build `apps/web` (node:22-alpine multi-stage, standalone) | 3000 | web |
| api      | build context `.` dockerfile `apps/api/Dockerfile` (python:3.12-slim) | 8000 | api |
| worker   | build `apps/worker` (python:3.12-slim) | — | worker |
| postgres | postgres:16-alpine | 5432 | postgres |
| n8n      | n8nio/n8n:latest | 5678 | n8n |

- Containers talk via service DNS (`http://api:8000`, `postgres:5432`). NEVER `localhost` inside containers.
- Volumes: `postgres_data:/var/lib/postgresql/data`, `n8n_data:/home/node/.n8n`.
- Bind mounts: `./storage:/app/storage` on **api and worker**; `./workflows/n8n:/workflows:ro` and `./storage:/files` on **n8n**.
- Healthchecks: postgres `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`; api via `python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/system/health', timeout=3).status==200 else 1)"`; web `wget -qO- http://127.0.0.1:3000` (busybox wget; NOT `localhost` — alpine resolves it to ::1 while the standalone server listens on IPv4 only).
- depends_on: api→postgres(healthy), worker→postgres(healthy), web→api(started), n8n→api(started).
- n8n env: `N8N_SECURE_COOKIE=false`, `N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}`, `GENERIC_TIMEZONE=Asia/Seoul`.
- web build arg: `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`) — baked at build time.

## 2. Environment (.env.example — exact keys)

```env
POSTGRES_DB=investment
POSTGRES_USER=investment_user
POSTGRES_PASSWORD=change_me

DATABASE_URL=postgresql+psycopg://investment_user:change_me@postgres:5432/investment

NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
INTERNAL_API_BASE_URL=http://api:8000

STORAGE_DIR=/app/storage

WORKER_POLL_INTERVAL_SECONDS=2

N8N_HOST=localhost
N8N_PORT=5678
N8N_PROTOCOL=http
N8N_ENCRYPTION_KEY=change_me
```

## 3. Database (init.md §6 verbatim; owned by api's Alembic migration 0001)

- `jobs(id UUID PK, job_type VARCHAR NOT NULL, status VARCHAR NOT NULL DEFAULT 'PENDING', payload JSONB, result JSONB, error_message TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`
- `job_logs(id UUID PK, job_id UUID FK→jobs.id ON DELETE CASCADE, level VARCHAR NOT NULL, step VARCHAR, message TEXT NOT NULL, metadata JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now())` — column name in ORM: use attribute `meta` mapped to column `metadata` if needed (SQLAlchemy reserves `metadata`).
- `imports(id UUID PK, job_id UUID FK→jobs.id, original_filename VARCHAR NOT NULL, stored_filename VARCHAR NOT NULL, file_path VARCHAR NOT NULL, file_size BIGINT NOT NULL, status VARCHAR NOT NULL DEFAULT 'PENDING', row_count INTEGER, created_at TIMESTAMPTZ NOT NULL DEFAULT now())`
- Indexes: `jobs(status, created_at)`, `job_logs(job_id, created_at)`, `imports(job_id)`.
- Enums as VARCHAR: job status `PENDING|RUNNING|SUCCESS|FAILED`; log level `INFO|WARNING|ERROR`; imports.status `PENDING|SUCCESS|FAILED`.
- UUIDs generated app-side (`uuid4`). `updated_at` maintained app-side. Times stored UTC.
- No `create_all` at app startup; schema only via `alembic upgrade head`.

## 4. Job lifecycle & types

Claim (worker, exact pattern):
```sql
SELECT id FROM jobs WHERE status = 'PENDING' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1;
```
then in the same transaction `UPDATE jobs SET status='RUNNING', started_at=now(), updated_at=now() WHERE id=:id`, commit, process, then final UPDATE to `SUCCESS` (set `result`, `finished_at`) or `FAILED` (set `error_message`, `finished_at`). Insert `job_logs` rows along the way (at minimum: claimed, finished/failed).

Job types (pinned names):
- **`TEST_JOB`** — sleep ~1s, write INFO logs, result `{"echo": <payload>, "processed_at": "<iso8601>"}`.
- **`CSV_IMPORT`** — payload `{"import_id": "<uuid>", "stored_filename": "...", "file_path": "raw/<stored_filename>", "original_filename": "..."}`. Worker: read `$STORAGE_DIR/<file_path>` (encoding `utf-8-sig`), validate required headers exactly `account_name,ticker,asset_name,quantity` (order-insensitive, extra columns allowed), ≥1 data row, `quantity` parses as number ≥ 0. On success: write normalized CSV (4 canonical columns) to `$STORAGE_DIR/processed/<stored_filename>`, update `imports` row → status SUCCESS + row_count, job result `{"row_count": N, "processed_path": "processed/<stored_filename>"}`. On failure: imports → FAILED, job → FAILED with clear `error_message`.
- Unknown job_type → job FAILED, error_message `Unknown job type: <type>`.

## 5. FastAPI endpoints (JSON shapes pinned)

Job JSON: `{"id","job_type","status","payload","result","error_message","created_at","started_at","finished_at","updated_at"}` (ISO8601 UTC, nulls allowed).

- `GET /system/health` → always 200: `{"status":"ok","database":"connected"}` or `{"status":"error","database":"disconnected"}` (DB checked with `SELECT 1`).
- `POST /api/v1/jobs/test` body optional `{"payload": {...}}` → 201, Job JSON (job_type `TEST_JOB`, status PENDING).
- `GET /api/v1/jobs?limit=20&offset=0&status=` → 200 `{"items":[Job...],"total":N,"limit":l,"offset":o}` ordered created_at DESC. limit max 100. Invalid status filter → 400.
- `GET /api/v1/jobs/stats` → 200 `{"total":N,"pending":N,"running":N,"success":N,"failed":N}`.
- `GET /api/v1/jobs/{job_id}` → 200 Job JSON + `"logs":[{"id","level","step","message","metadata","created_at"}]` (created_at ASC). Missing → 404 JOB_NOT_FOUND. Malformed UUID → 400 VALIDATION_ERROR.
- `POST /api/v1/imports/csv` multipart field **`file`** → 201 `{"job_id":"...","import_id":"...","original_filename":"..."}`. Non-.csv extension → 400 `INVALID_FILE_TYPE`; empty file → 400 `EMPTY_FILE`. Saves to `storage/raw/<uuid4hex>_<sanitized_original>`, creates imports row (PENDING) + CSV_IMPORT job (PENDING) — content validation happens in worker.
- `POST /internal/jobs` body `{"job_type":"...","payload":{...}}` → 201 Job JSON. job_type must be non-empty string; payload optional. (Separate router; no auth this phase.)

Error envelope (all non-2xx): `{"error":{"code":"...","message":"...","details":{...}}}`. Codes: `VALIDATION_ERROR`, `JOB_NOT_FOUND`, `INVALID_FILE_TYPE`, `EMPTY_FILE`, `INVALID_CSV`, `INTERNAL_ERROR`. FastAPI/pydantic 422s must be reformatted into this envelope (keep 422 status). Never leak stack traces.

**CORS: allow origin `http://localhost:3000`** (methods *, headers *).

## 6. Python stack pins

api: python 3.12, fastapi, uvicorn[standard], sqlalchemy>=2.0, alembic, psycopg[binary]>=3.1, pydantic>=2, pydantic-settings, python-multipart, pytest, httpx (pin exact versions you know exist; one requirements.txt per app, test deps included).
worker: sqlalchemy>=2.0 + psycopg[binary] only (raw SQL via engine; no ORM models, no alembic).
Settings from env: `DATABASE_URL`, `STORAGE_DIR`, worker also `WORKER_POLL_INTERVAL_SECONDS`. Worker retries DB connection at startup (loop, ~2s interval, give up after ~60s with clear error). Graceful SIGTERM/SIGINT stop.

api Dockerfile (context = repo root): COPY `apps/api/requirements.txt` → pip install; COPY `apps/api/` → `/app`; COPY `database/` → `/app/database`; COPY `alembic.ini` → `/app/alembic.ini`; WORKDIR `/app`; CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000`. So `docker compose exec api alembic upgrade head` works (cwd /app; alembic.ini `script_location = database/migrations`; env.py reads DATABASE_URL from env).
Tests land at `/app/tests` → `docker compose exec -T api pytest -q` and `docker compose exec -T worker pytest -q` must pass. Tests derive a test DB URL by swapping the db name to `investment_test` (create DB if missing via autocommit connection; build schema with metadata.create_all or the migration; truncate between tests).

## 7. Web (Next.js) pins

- Next.js 15 (app router) + TypeScript strict + Tailwind **3.4** + TanStack Query v5. React 19. `output: "standalone"`.
- No Radix. Hand-vendored shadcn-style components under `components/ui/` (button, card, badge, table, skeleton, input at minimum) using cva/clsx/tailwind-merge.
- All dashboard pages are client components; data fetched browser-side from `process.env.NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`). Central typed API client in `lib/`.
- Routes: `/` = Overview, `/data-operations`, `/settings` (sidebar layout per init.md §10: Overview, Data Operations, Settings).
- Overview: health poll (refetch 5s), stats cards from `/api/v1/jobs/stats`, recent 5 jobs. Data Operations: run-test-job button, CSV upload (multipart `file`), jobs table (refetch 3s), job detail view with logs (poll while RUNNING). Settings: read-only API URL + env info.
- Required UI states: loading (skeleton), success, empty list, API unreachable (banner/error state), failed job (visible error message). English labels.
- Docker: multi-stage node:22-alpine; `ARG NEXT_PUBLIC_API_BASE_URL` before build; run standalone `node server.js`, port 3000.

## 8. Design system (from DESIGN.md → Tailwind tokens)

- Page canvas `#f6f5f4` (warm paper); content surfaces `#ffffff`; hairline borders `#e6e6e6`; text ink `#000000` (95% alpha ok), secondary `#31302e`, muted `#615d59`, faint `#a39e98`.
- Single structural accent: **Notion blue `#0075de`** (primary buttons, links, active nav indicator, focus). Pressed `#005bab`. No second structural accent.
- Status colors (semantic, badges/dots only): SUCCESS `#1aae39`, RUNNING `#62aef0`, PENDING `#615d59` (muted), FAILED `#e03e3e` (palette extension — DESIGN.md has no error color).
- Font: Inter (next/font/google), negative tracking on large headings. Radii: inputs 4px, buttons/utility 8px, cards 12px. Elevation: hairline + barely-there shadow; no heavy drop shadows. Sidebar on canvas-soft, content area white-card based, generous whitespace, quiet monochrome + one blue.

## 9. File ownership (conflict prevention)

| owner | paths |
|---|---|
| pi-infra | docker-compose.yml, .env.example, .gitignore, Makefile, README.md, scripts/*, workflows/n8n/*, storage/*/.gitkeep, database/seeds/.gitkeep |
| pi-api | apps/api/**, alembic.ini (root), database/migrations/** |
| pi-worker | apps/worker/** |
| pi-web | apps/web/** |

Nobody touches `init.md`, `DESIGN.md`, `personal_investment_dashboard_architecture.md`, `CLAUDE.md`, this file, or another owner's paths. No git commits (lead commits). No `docker build/up` during build phase (verify stage does it).
