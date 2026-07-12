# Kiwoom Integration Contract (BINDING — round 2)

Extends `contract.md` (round 1 stays in force). Pins every interface for the Kiwoom REST API portfolio sync. Builders implement AGAINST this; renegotiation goes through the lead.
Source plan: user's Kiwoom design doc + lead's evaluation (2026-07-12). Kiwoom endpoint/field truth comes from `docs/architecture/kiwoom-api-reference.md` (written by kw-docs from OFFICIAL docs; never guess field names).

## 0. Scope decisions (already made — do not reopen)

- REST API only (no OpenAPI+/COM). Read-only TRs: accounts, balances, positions, deposits. No orders.
- Portfolio UI lives on the EXISTING first screen `/` (`apps/web/app/page.tsx`), portfolio section on top, existing system/jobs section stays below. NO `/overview` route.
- Web stays client-component + browser fetch pattern (no SSR fetching this round).
- Frontend files under `components/portfolio/` + `lib/api.ts` extension (NOT a new `features/` tree).
- Worker stays raw-SQL style (SQLAlchemy text() + `ON CONFLICT` upserts). ORM models for the new tables live in the API app only.
- Tables in the `public` schema, names as §3. `assets` unique on (country, market, ticker); `asset_identifiers` deferred.
- Idempotency = query jobs for existing PENDING/RUNNING SYNC_KIWOOM_PORTFOLIO with same connection_id; no time_bucket key.
- ~~US equities: build IF kiwoom-api-reference confirms REST support~~ → **SUPERSEDED 2026-07-12 (round 2b): US REST IS CONFIRMED LIVE.** The precondition is met, so US is now IN SCOPE and `us_supported` must become `true`. See §10 (US addendum, binding).
- n8n: manual-trigger workflow only this round (schedules documented, added after keys work).
- Without configured keys, everything still runs: UI shows "키 미설정" state; a sync job FAILS cleanly at step `validate_configuration` with a clear message. This is the E2E we verify pre-keys.

## 1. Env & settings

`.env.example` additions (kw-infra):
```env
KIWOOM_APP_KEY=
KIWOOM_SECRET_KEY=
KIWOOM_API_BASE_URL=https://api.kiwoom.com
KIWOOM_ENVIRONMENT=REAL

INTERNAL_API_KEY=change_me_internal
```
docker-compose (kw-infra): worker env += the 4 KIWOOM_*; api env += INTERNAL_API_KEY; n8n env += INTERNAL_API_KEY (workflows reference `{{ $env.INTERNAL_API_KEY }}`; if n8n blocks env access set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`).
NOTE: `.env` already exists on the machine — new keys must be APPENDED (verify stage does `awk`-append of missing keys from .env.example; README documents it for the user).

## 2. Internal API auth

- Dependency on the `/internal` router only: header `X-Internal-API-Key` must equal `settings.internal_api_key`. Missing/wrong → 401 envelope code `UNAUTHORIZED`. Applied to ALL /internal routes.
- Ripple effects (owners): apps/api/tests (kw-api), scripts/integration-test.sh sends the header — value read from .env (kw-infra), workflows/n8n/create-test-job.json gains the header via $env (kw-infra).

## 3. New tables (migration `0002_kiwoom_portfolio` in database/migrations/versions/, models in apps/api/app/models.py — kw-api owns both)

Common: UUID PKs app-side uuid4; TIMESTAMPTZ; created_at/updated_at defaults as round 1. Money/qty types: quantity & prices `NUMERIC(20,6)`, amounts `NUMERIC(20,2)`, exchange_rate `NUMERIC(12,4)` NULLABLE, unrealized_return `NUMERIC(10,4)` NULLABLE. KRW-converted fields NULLABLE (US rows may lack FX until rate known; domestic uses rate 1.0).

- `brokers(id, code UNIQUE, name, is_active, created_at, updated_at)`
- `brokerage_connections(id, broker_id FK, connection_name, environment, status, last_connected_at, last_synced_at, last_error TEXT, created_at, updated_at)` — status ∈ CONFIGURED|CONNECTED|ERROR. No credentials columns (env only).
- `accounts(id, broker_id FK, brokerage_connection_id FK, external_account_id, account_number_masked, account_name, account_type, base_currency, is_active, last_synced_at, created_at, updated_at)` UNIQUE(brokerage_connection_id, external_account_id)
- `assets(id, country, market, ticker, name, asset_type, currency, is_active, created_at, updated_at)` UNIQUE(country, market, ticker)
- `current_positions(id, account_id FK, asset_id FK, quantity, available_quantity, average_purchase_price, purchase_amount_local, current_price, market_value_local, unrealized_pnl_local, unrealized_return, exchange_rate, market_value_krw, unrealized_pnl_krw, as_of, source_job_id, created_at, updated_at)` UNIQUE(account_id, asset_id)
- `account_balances(id, account_id FK, currency, cash_balance, available_cash, total_purchase_amount_local, total_market_value_local, total_evaluation_amount_local, total_unrealized_pnl_local, exchange_rate, total_evaluation_amount_krw, as_of, source_job_id, created_at, updated_at)` UNIQUE(account_id, currency)
- `portfolio_snapshots(id, account_id FK, snapshot_at, base_currency, cash_value_krw, securities_value_krw, total_assets_krw, total_purchase_amount_krw, total_unrealized_pnl_krw, source_job_id, created_at)` INDEX(account_id, snapshot_at)
- `position_snapshots(id, portfolio_snapshot_id FK, account_id, asset_id, currency, quantity, average_purchase_price, current_price, market_value_local, market_value_krw, unrealized_pnl_local, unrealized_pnl_krw, exchange_rate, created_at)` INDEX(portfolio_snapshot_id)
- `broker_api_raw_responses(id, broker_id FK, job_id, api_category, endpoint_name, response_file_path, response_hash, received_at, created_at)` INDEX(job_id)

Migration 0002 also SEEDS (idempotent inserts): brokers(code='KIWOOM', name='키움증권') and one brokerage_connections row (connection_name='키움 기본 연결', environment='REAL', status='CONFIGURED').

## 4. Job `SYNC_KIWOOM_PORTFOLIO` (kw-worker)

payload: `{"connection_id": "<uuid or null>", "force_refresh": false}` — null connection_id → first active connection.
Step log sequence (job_logs `step` values, in order):
`validate_configuration, request_access_token, fetch_accounts, fetch_domestic_balance, fetch_domestic_positions, fetch_us_balance, fetch_us_positions, save_raw_responses, normalize_assets, upsert_accounts, upsert_positions, create_snapshots, complete`
(us steps log SKIPPED via INFO when unsupported/unconfigured rather than being omitted silently.)

result: `{"accounts_synced": n, "domestic_positions": n, "us_positions": n, "cash_balances": n, "snapshots_created": n, "us_supported": bool, "synced_at": iso}`

Behavior pins:
- Keys unset/blank → FAILED at validate_configuration, error_message `KIWOOM_APP_KEY/KIWOOM_SECRET_KEY is not configured` (exact enough for UI). connection.status→ERROR + last_error.
- Token: module-level cache {token, expires_at}; reuse while >60s remains; never write token to disk/DB/logs. `token-metadata.json` in raw dir contains issued_at/expires_at ONLY.
- Rate limit: ≥250ms sleep between TR calls; on 429/limit response retry ×3 with backoff (1s/2s/4s).
- Raw BEFORE db: save each response as JSON under `storage/raw/kiwoom/YYYY/MM/DD/<job_id>/<name>.json`, register each in broker_api_raw_responses (path relative to STORAGE_DIR, sha256 hash). Secrets/token never in files; log lines never contain appkey/secret/token/full account numbers.
- DB write: per-account single transaction — upsert account, balances(by currency), assets, current_positions (ON CONFLICT (account_id,asset_id) DO UPDATE), DELETE current_positions rows for that account absent from this sync, insert portfolio_snapshot + position_snapshots. All-or-nothing per account.
- Success → connection.status=CONNECTED, last_connected_at, last_synced_at. Partial (domestic ok, us fail) → job FAILED with clear message but domestic data committed (per-account tx), connection.status=ERROR + last_error. Unexpected response shape → pydantic validation error → FAILED with "unexpected response shape (raw saved: <path>)".

## 5. Worker structure & deps (kw-worker owns apps/worker/**)

```
apps/worker/
├── brokers/kiwoom/{auth.py, client.py, domestic.py, us_equities.py, adapter.py, exceptions.py, schemas/{auth.py, domestic.py, us_equities.py}}
├── handlers/sync_kiwoom_portfolio.py   (+ register "SYNC_KIWOOM_PORTFOLIO" in handlers/__init__.py)
├── repositories/{accounts.py, assets.py, balances.py, positions.py, snapshots.py, raw_responses.py}  (thin modules of textual SQL)
└── (existing files unchanged in behavior)
```
- Handler signature MUST match existing: `run(engine, job_id, payload, storage_dir, log_job)`.
- requirements.txt += `httpx` and `pydantic` (pin exact real versions).
- pydantic schemas: `extra="allow"`, explicit field mapping in adapter (kiwoom field → internal model), grounded in kiwoom-api-reference.md. Where the reference marks a field TO-VERIFY, adapter must tolerate absence (None) rather than KeyError.
- Internal position model = plan §6 field list (account_id, asset_id, broker, country, market, ticker, asset_name, asset_type, currency, quantity, available_quantity, average_purchase_price, purchase_amount_local, current_price, market_value_local, unrealized_pnl_local, unrealized_return, exchange_rate, market_value_krw, unrealized_pnl_krw, as_of, source_job_id). Domestic: country=KR, market=KRX, currency=KRW, exchange_rate=1.0. US: country=US, market from response (NASDAQ/NYSE/AMEX), currency=USD.
- Tests (in-container vs test DB): conftest DDL += all 9 tables (mirror §3). Unit tests mock httpx (respx or monkeypatch) with fixtures derived from kiwoom-api-reference examples: token issue, domestic happy path (≥2 positions), missing-keys failure, position-removed-on-next-sync (sold stock deleted), unexpected-shape failure, rate-limit retry. NO live API calls in tests.

## 6. API endpoints (kw-api owns apps/api/**; JSON pinned)

Position JSON: the §5 internal model fields, camel/snake — use snake_case like round 1, ISO8601 UTC.

- `GET /api/v1/brokerage-connections` → 200 `{"items":[{"id","broker_code","connection_name","environment","status","last_connected_at","last_synced_at","last_error","credentials_configured": bool}]}` — credentials_configured = both KIWOOM_APP_KEY and KIWOOM_SECRET_KEY non-empty in api settings. For this to work, kw-infra adds KIWOOM_APP_KEY/KIWOOM_SECRET_KEY to the **api service env as well** (presence check only; the api never calls Kiwoom).
- `GET /api/v1/brokerage-connections/{id}` → single object, 404 CONNECTION_NOT_FOUND.
- `POST /api/v1/brokerage-connections/{id}/sync` → creates SYNC_KIWOOM_PORTFOLIO job. Existing PENDING/RUNNING job for this connection (jobs.payload->>'connection_id') → 200 `{"job_id","status","reused":true}`; else 202 `{"job_id","status":"PENDING","reused":false}`.
- `GET /api/v1/portfolio/overview` → 200:
```json
{
  "summary": {"total_assets_krw","securities_value_krw","cash_value_krw","total_purchase_amount_krw","total_unrealized_pnl_krw","unrealized_return_pct","position_count","account_count"},
  "accounts": [{"id","account_name","account_number_masked","account_type","base_currency","total_assets_krw","last_synced_at"}],
  "positions": [Position...],
  "cash_balances": [{"account_id","currency","cash_balance","available_cash","total_evaluation_amount_krw","as_of"}],
  "market_breakdown": [{"country","securities_value_krw","position_count"}],
  "last_synced_at": null|iso,
  "sync_status": "NEVER_SYNCED"|"SUCCESS"|"FAILED"|"RUNNING",
  "connection": {"id","status","credentials_configured","last_error"}
}
```
  sync_status: RUNNING if a SYNC job PENDING/RUNNING; else last SYNC job's status; NEVER_SYNCED if none. Empty DB → zeros/empty arrays (NOT 404). Numeric NUMERIC → serialize as string? NO — serialize as JSON number (float) for UI simplicity; document precision caveat.
- `GET /api/v1/portfolio/positions?account_id&country&currency` → `{"items":[Position],"total"}` sorted market_value_krw DESC NULLS LAST. Invalid filter value → 400 VALIDATION_ERROR.
- `GET /api/v1/accounts/{account_id}/portfolio` → account-scoped overview subset `{"account","positions","cash_balances","last_synced_at"}`, 404 ACCOUNT_NOT_FOUND.
- New error codes: UNAUTHORIZED, CONNECTION_NOT_FOUND, ACCOUNT_NOT_FOUND (same envelope).
- Tests: update existing /internal tests for the auth header; add tests for connections list, sync create+reuse, overview empty-state, positions filters, 401 without header.

## 7. Web (kw-web owns apps/web/**)

`/` page top-to-bottom: ① Portfolio header bar — connection status chip(키 미설정→muted "연결 대기 · API 키를 .env에 설정하세요" / CONFIGURED→"연결 준비됨" / CONNECTED→green / ERROR→red + last_error tooltip/text), last_synced_at, [키움 계좌 동기화] primary button (disabled while RUNNING; after POST poll GET /api/v1/jobs/{id} 2s until terminal → invalidate portfolio queries; FAILED → show error_message inline). ② Summary cards (총자산/주식 평가금액/현금·예수금/총매입금액/평가손익+수익률/보유종목 수). ③ Market·currency cards (국내주식 평가금액 / 미국주식 평가금액 / KRW 예수금 / USD 예수금). ④ Positions table — columns per plan §12.5, default sort 원화환산 평가금액 DESC, filters (전체/국내/미국 segmented + 계좌 select + 통화 select), 비중 = market_value_krw / sum. ⑤ Data status panel (마지막 동기화, 최근 SYNC 작업 상태, 최근 오류, raw 출처 카운트는 생략 가능). ⑥ Existing system-status + recent jobs content remains BELOW.
- Empty/NEVER_SYNCED state: friendly setup card — "1. .env에 KIWOOM_APP_KEY/SECRET 입력 → 2. docker compose up -d --force-recreate worker api → 3. 동기화 버튼" (exact copy can vary, steps must match README).
- All client components; new API fns+types in lib/api.ts; components in components/portfolio/*; design tokens unchanged (round-1 §8; pnl 양수는 status-success, 음수는 status-failed 색 재사용, 그 외 색 추가 금지).
- MUST validate: npm install(변경 없으면 생략 가능) + `npx tsc --noEmit` + `npm run build` green before reporting.

## 8. n8n & scripts (kw-infra)

- `workflows/n8n/portfolio/sync-kiwoom-portfolio.json`: TOP-LEVEL `"id": "sync-kiwoom-portfolio"` (CLI import requires it), name "Sync Kiwoom Portfolio", Manual Trigger → HTTP Request POST http://api:8000/internal/jobs, headers: X-Internal-API-Key = `={{ $env.INTERNAL_API_KEY }}`, json body `{"job_type":"SYNC_KIWOOM_PORTFOLIO","payload":{}}`. Update `create-test-job.json` with the same header. Both must pass `n8n import:workflow`.
- `scripts/integration-test.sh` updates: read INTERNAL_API_KEY from .env; add header to /internal/jobs step; NEW steps: (a) GET /api/v1/portfolio/overview → 200 & sync_status field present; (b) GET /api/v1/brokerage-connections → 1 item, credentials_configured=false (pre-keys CI reality); (c) POST /api/v1/brokerage-connections/{id}/sync → job created; poll until FAILED and error mentions "not configured" (THIS IS EXPECTED PASS pre-keys — print clearly "PASS: sync fails cleanly without keys"). Keep existing steps green.
- `workflows/n8n/README.md` += new workflow entry + note on adding Schedule Trigger later (장전 08:30 / 장후 16:00 / 미장후 06:30 KST 예시).
- `README.md` += "키움 API 키 설정" 섹션: 키움 REST API 신청 경로(키움증권 홈페이지 → Open API 신청), .env 4개 키 입력, `docker compose up -d --force-recreate api worker`, 대시보드에서 동기화 버튼, 문제 시 Data Operations 작업 로그 확인.

## 10. US equities addendum (round 2b — BINDING, supersedes the §0 NOT_SUPPORTED decision)

Confirmed live (2026-07-12, read-only probe with real keys; all return_code=0):
- `POST /api/us/acnt` with api-id `ust21070` (해외 잔고), `ust21110` (해외 예수금), `ust21160` (예수금 상세). No account number in the request (appkey is account-bound, same as domestic).
- `ust21070` → top-level `tot_evlt_amt(_krw)`, `tot_prch_amt(_krw)`, `tot_pl_amt(_krw)`, `tot_pl_rt`; `result_list[]` per holding: `stk_cd`, `frgn_stk_nm`, **`poss_qty`** (⚠️ see below), `qty`, `sell_alowq`, `frgn_stk_book_uv` (매입단가), `now_pric`, `evlt_amt`, `pl_amt`, `pl_rt`, `evlt_amt_krw`, `pl_amt_krw`, `exch_rate`, `natn_nm`, `stex_nm`.
- ⚠️ **quantity = `poss_qty`, NOT `qty`.** `qty` omits unsettled buys. Live proof: SKHYV `qty`=0 / `poss_qty`=2 — using `qty` silently DROPS a 504,030 KRW position; GLW `qty`=1 / `poss_qty`=4. `evlt_amt / now_pric == poss_qty` on every row.
- `ust21110` → `krw_entra` + `result_list[{crnc_code, fc_entra, fc_pymn_alowa, fc_ord_alowa, fc_booka}]`. **It carries NO FX rate.**
- **`ust21160` is REQUIRED** (not optional): it is the only source of BOTH `usd_exch_rate` (comma-formatted, e.g. "1,484.10") AND the settled **D+2** USD balance (`d2_usd_fx_entr`).

Pins:
- **KRW conversion comes FROM KIWOOM** (`evlt_amt_krw`, `pl_amt_krw`, `exch_rate`). NEVER compute or guess FX. Store `exchange_rate` per position from `exch_rate`.
- ⚠️ **Kiwoom uses TWO different USD rates and both are authoritative — do not unify them.** Positions: `exch_rate` = **1500.00** flat (Kiwoom's own `evlt_amt_krw` is computed with it — matching HTS). USD cash: `usd_exch_rate` = **1,484.10** (ust21160). Storing either one over the other would misstate money. Kiwoom also rounds each holding's KRW separately AND the grand total separately, so Σ(rows) ≠ their total by ±1~60 KRW — that is THEIR rounding; do not "fix" it by recomputing.
- **assets.market for US = `"US"`** (constant) — the response carries no NASDAQ/NYSE field (only `stex_nm`/`natn_nm`); use `stex_nm` ONLY if it cleanly yields NASDAQ/NYSE/AMEX, else `"US"`. This supersedes §5's "market from response". country=`"US"`, currency=`"USD"`, ticker = `stk_cd` normalized (strip any exchange suffix/prefix; keep the plain symbol, e.g. GOOGL).
- **USD cash row**: `account_balances` (UNIQUE account_id+currency) gets a USD row. `exchange_rate` = `usd_exch_rate` (ust21160) so USD cash CAN be counted in KRW totals (previously NULL/excluded). Do **NOT** repurpose `total_evaluation_amount_*` for this (see the ⚠️ below).
- ⚠️ **USD `cash_balance` = the SETTLED D+2 balance (`ust21160.d2_usd_fx_entr`), NOT `fc_entra` (D+0).** Live proof: fc_entra 4,905.44 vs d2 3,976.74; the 928.70 gap is exactly the pending buys (`d1+d2_usd_buy_excta`) for shares ALREADY counted in `poss_qty`. Using fc_entra double-counts **1,378,284 KRW** — the same bug class as the domestic `entr`/D+2 trap. (An earlier draft of this section said fc_entra; that was WRONG, caught live by kw-worker.) A negative D+2 KRW balance (e.g. −1,027 after a KRW→USD 환전) is truthful, not a bug.
- ⚠️ **`account_balances.total_evaluation_amount_local/_krw` is Kiwoom's 추정예탁자산 — an ACCOUNT-level total (cash + securities), NOT the cash row's KRW value.** Live proof: KRW row has `cash_balance` 2,495 but `total_evaluation_amount_krw` 6,597,287 (≈ the securities). **Never use it as cash** — doing so double-counts securities and doubles 총자산 (this is the same class of bug as the `entr` double-count). It may only be surfaced as a reconciliation figure (키움 추정예탁자산) or ignored.
- ⚠️ **"Never sum 추정예탁자산 as cash" applies to EVERY consumer, not just the API.** It bit in three places: (1) the API summary, (2) the worker's `account_balances` writes, and (3) **`portfolio_snapshots.cash_value_krw`**, which was summing that column — fixing only (1) and (2) would have relocated the double-count into the snapshot table (총자산 would have read ~51.9M instead of 45.3M). Every cash total, in any layer, is `Σ(cash_balance × exchange_rate)`. Snapshot and API summary must agree by construction.
- ⚠️ **KRW cash row must stay = `kt00001.d2_entra` (settled D+2 cash).** `ust21110.krw_entra` is a different figure; because `account_balances` is UNIQUE(account_id, currency), upserting it would silently OVERWRITE the correct KRW row and re-introduce the double-count. Take the USD row from the US TR; leave the KRW row to `kt00001`.
- Job result: `us_supported: true`, `us_positions: n`. Steps `fetch_us_balance` / `fetch_us_positions` do real work (no more SKIPPED). Raw responses saved per §4 naming (`ust21070_balance_*.json` etc.).
- Partial-failure rule (§4) stands: domestic committed per-account tx; a US failure still FAILS the job with a clear message and connection→ERROR, but domestic data stays.

Summary/aggregation corrections (kw-api, binding):
- `summary.total_purchase_amount_krw` MUST be the real purchase total (sum of positions' purchase amounts in KRW / Kiwoom's `tot_pur_amt` + `tot_prch_amt_krw`) — **NOT** the old derivation `securities − pnl` (which was off by 15,248 KRW live).
- `summary.cash_value_krw` = **Σ(cash_balance × exchange_rate)** over balance rows; KRW rate defaults to 1.0 when null; a row with no rate contributes 0 (never guess FX). ~~Σ(total_evaluation_amount_krw where present…)~~ — **that earlier formula was WRONG** (it summed 추정예탁자산 = cash + securities into "cash"; caught by kw-web before shipping).
- `CashBalanceOut` MUST expose `exchange_rate` (nullable) and `cash_krw` (= cash_balance × exchange_rate, null when no rate) so the UI can show a USD card's KRW sub-line without inventing FX.
- `market_breakdown` must list both KR and US rows.
- Reconciliation invariant (verify stage): `summary.total_assets_krw` ≈ (키움 국내 tot_evlt_amt + 미국 tot_evlt_amt_krw) + (D+2 KRW cash + USD cash × FX). It must NOT approach the sum of those plus 추정예탁자산.

## 9. File ownership (round 2)

| owner | paths |
|---|---|
| kw-docs | docs/architecture/kiwoom-api-reference.md |
| kw-api | apps/api/**, database/migrations/versions/0002_*.py |
| kw-worker | apps/worker/** |
| kw-web | apps/web/** |
| kw-infra | docker-compose.yml, .env.example, scripts/*, workflows/n8n/**, README.md |
| lead | this file, contract.md pointer, commits |

Round-1 rules stay: LF endings, no git commits by builders, no docker build/up during build phase (verify does it), no scope creep beyond this contract, existing files' style respected.
