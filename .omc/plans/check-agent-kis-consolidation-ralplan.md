# CHECK-agent KIS Consolidation — iNAV Component-Price Feed (RALPLAN-DR)

**Status: PENDING APPROVAL (v1)** · Mode: **DELIBERATE** · Schema: **price-feed (locked)** · Scope: **phased-full, Phase 1 first (locked)** · Ownership: **CHECK owns the KIS account; server MAY depend on CHECK (locked)**

> PLAN ONLY. The live collector process must not be touched. This document is for Architect/Critic review before any implementation.

Repo: `\\wsl.localhost\Ubuntu\home\user\projects\personal-investment-platform` · Service: `apps/collector` · api proxy: `apps/api`

---

## 0. One-paragraph intent

Move the collector's realtime iNAV **component-price** lane (KIS WebSocket delayed ticks + overseas/domestic REST snapshots + prev-close daily-bar pinning) out of the server. The external **CHECK agent** — which already owns the KIS account and posts the 호가 envelope — becomes the single owner of the KIS realtime session and **pushes raw per-symbol prices** to the server over HTTP. The server **keeps its iNAV/deviation engine** and simply feeds the pushed prices into the existing `bulk_update_from_snapshots` seam. Phase 1 delivers exactly this component-price lane (the urgent approval_key/WS conflict); Phase 2 (calm window) migrates the ETF-quote lane, WRAP, prev-close ownership, and basket ownership until the server has **zero** live KIS consumption.

---

## 1. RALPLAN-DR Summary

### Principles (5)
1. **Correctness retention over relocation.** The migration must not lose the server's recent day-session (NAS/NYS/AMS→BAQ/BAY/BAA) remap and prev-close-pin fixes. Equivalence is **parity-gated** before any flip.
2. **One owner per KIS session.** Exactly one machine holds the KIS WS/approval_key. The server's WS lane is **retired (not scheduled), not duplicated** — this is the direct fix for the "no close frame" death.
3. **Server owns identity; CHECK owns prices.** The ISIN↔(exchange,symbol) resolution stays server-side (it needs **no live KIS** — see §3 finding) and is published via a new `GET /watchlist`. CHECK prices strictly by those authoritative keys.
4. **Fail-stale, never fail-stop.** A stalled/absent feed keeps last-good prices and lets age grow; the process never crashes; the KIS-direct path stays intact for **instant flag rollback**.
5. **Phased, reversible, flag-gated, channel-separated.** Default stays KIS-direct; the feed lives behind an env flag mirroring `COLLECTOR_ALLOW_TOKEN_ISSUE`. The 1s 호가 channel and the (new) price channel stay **separate** — prices are never merged into the 1s 호가 envelope.

### Decision Drivers (top 3)
1. **Resolve the KIS approval_key / WS conflict** ("no close frame") that killed realtime overseas ticks. Two WS sessions on one app key cannot coexist — urgent.
2. **Preserve engine correctness + last-good + parity + version-pinned in-container engine.** The server's engine has recent, hard-won fixes; keep them and keep the ability to compare feed vs KIS-direct.
3. **Key-mapping is local-cache-only (no live KIS).** Confirmed: this unblocks dropping **all** live KIS from the component lane while resolution stays server-side, making Phase 1 a clean full-lane migration rather than a partial one.

### Viable Options (schema fork)

**Option A — price-feed (CHOSEN, user-locked).**
CHECK pushes raw per-symbol prices (`last`, `base`, `currency`, `trade_time`) keyed by **server-canonical** `(exchange, symbol)`; the server keeps the iNAV/deviation engine and ingests via the existing `bulk_update_from_snapshots` seam.
- Pros: correctness retained on the server; **last-good** serving on CHECK downtime; **parity-able** (engine-vs-engine on identical inputs); minimal engine change (reuses an existing seam); trivial rollback (flag flip); version-pinned engine stays in-container.
- Cons: server depends on CHECK for realtime prices in-session (accepted per locked ownership decision); CHECK must own the day-session remap + a stable prev-close `base`; a wire contract now spans two codebases/machines.

**Option B — result-feed (INVALIDATED — rationale, not re-argued).**
CHECK computes iNAV/deviation and the server just serves it.
- **Why invalidated:** (i) discards the server's recent BAQ/BAY/BAA day-session + prev-close-pin fixes — they'd have to be re-implemented and re-validated inside CHECK, a **separate codebase we do not own**; (ii) **no last-good / degraded serving** when CHECK is down — the server would have nothing to compute from; (iii) **no parity path** — you cannot compare an engine against itself if only one side has an engine; (iv) relocates the **version-pinned engine off-container**, coupling CHECK to basket math + PDF resolution. Recorded here to satisfy the RALPLAN-DR ≥2-viable-options rule; the user has locked Option A.

**Sub-option B1 — ISIN-keyed ingest** (CHECK supplies ISIN→price via `update_price(isin, …)`, engine.py:218). Rejected as the primary path: it **duplicates** the server's authoritative resolution and risks ISIN/key drift. Retained only as a narrow fallback for a symbol that genuinely cannot be `(exchange,symbol)`-keyed. Primary path keeps a single source of truth via `/watchlist` + `(exchange,symbol)` keys.

**Sub-option A1 — split lane** (keep domestic KRX/KFO components on server KIS REST, move only overseas). Deferred, not chosen for Phase 1: it leaves a server REST token issuing against the shared app key (token-ownership ambiguity vs CHECK) and leaves a partial `_price_loop`. Primary Phase-1 moves the **entire** `_fetch_kis_snapshots` output (overseas + domestic non-Taiwan components) to the feed for a clean `_price_loop` replacement. Taiwan (TWSE/TPEX) is **not KIS** and stays server-side unchanged.

---

## 2. Context

The collector (`apps/collector/collector/main.py`) runs an asyncio orchestrator: FX loop, KIS REST price loop, TWSE loop, ETF-quote loop, WRAP loop, GURU[13F] loop, a KIS realtime WebSocket lane, a 1s compute loop, and an in-process FastAPI on `0.0.0.0:8100`. The collector has **no host port** in `docker-compose.yml` (service `collector`, profile-gated) — it is reachable only inside the compose network. The `api` service (`apps/api`, host `:8000`) proxies collector reads (`/api/v1/inav/*`, inav.py) and forwards the CHECK 호가 POST (`/internal/check/hoga` → collector `/ingest/hoga`, internal.py:44).

The 호가 push template already exists and is the model for this migration:
- Producer path: CHECK → api `POST /internal/check/hoga` (guarded by `X-Internal-Api-Key == INTERNAL_API_KEY`, 2s wall-clock budget, fast 503 when collector down — internal.py:16,44-66) → collector `POST /ingest/hoga` (main.py:1063) → `state.update_hoga(envelope)` (state.py:176, seq gate) → served `GET /hoga` (main.py:1071) and merged under a **15s freshness gate** in `_build_summary_rows` (main.py:604-612).
- Envelope schema `CheckHogaEnvelope` (schemas.py:17): `{schema_version:int, source:str, source_timestamp:str, sent_at:str, seq:int|None, payload:dict}` — `payload` is a loosely typed pass-through the collector owns.

The realtime iNAV **component-price** lane we are migrating:
- `_fetch_kis_snapshots` (main.py:340) → REST overseas+domestic snapshots, 15s via `_price_loop` (main.py:816), with the US day-session remap and prev-close overwrite.
- `_refresh_us_prev_closes` (main.py:305) → KIS daily bars (HHDFS76240000), pins prev-close once/KST-day.
- WS lane: `_ws_loop` (main.py:950) / `_rotation_loop` (927) / `_ws_receiver` (896) / `_parse_hdfscnt0_ticks` (143) / `KisWebSocket` (kis_api/websocket_client.py) / `approval_key` (kis_api/auth.py:113). **This WS + the shared approval_key is the "no close frame" conflict source.**
- Engine seam: `InavEngine.bulk_update_from_snapshots(snapshots: list[dict]) -> int` (engine.py:308) → `update_price_by_key(exchange,symbol,snap)` (engine.py:223) → `_merge_snapshot` (engine.py:230). Reads `exchange, symbol` (uppercased, must exist in `_key_to_isin`), then `last, base, currency, trade_time`. WS tick path is `update_last_by_key` (engine.py:270).

---

## 3. Grounded findings from this investigation (build on these)

**FINDING 1 — key-mapping needs ZERO live KIS (resolves coupling (a)).**
`legacy_inputs.sync_master()` (legacy_inputs.py:144-174) is a `shutil.copyfile` from the `:ro` legacy mount `/srv/legacy/etf_data/cache/master/*.parquet` into the writable `/app/.cache/master` — a **local parquet copy, not a KIS API call**. `resolve_instruments` (kis_prices.py:166-279) builds instruments from `KisMaster.lookup` (that parquet) + `fetch_ticker_by_isin` (OpenFIGI, a **third-party** API, cached in the KisStore SQLite copied by `sync_db`, legacy_inputs.py:178). Neither touches the KIS **trading account / token / approval_key**. The engine's `_key_to_isin` (engine.py:144-155) is derived purely from these. **Therefore the server keeps ISIN↔(exchange,symbol) resolution server-side with no live KIS, and Phase 1 can drop ALL live KIS from the component lane** (WS + snapshot REST + prev-close daily bars). (KisMaster's download-on-cache-miss pulls **public static `.mst` master files**, not the trading API — still no token/approval; in normal operation `sync_master` pre-stages so no download occurs.)
Decision: **server keeps the KIS-master/OpenFIGI resolution and publishes the resolved keys via `/watchlist`.** No ISIN-keyed ingest path is needed for the primary flow.

**FINDING 2 — WS and REST share the same app key (auth.py).**
`approval_key()` (auth.py:113) and `access_token()` (auth.py:75) both use the same `app_key`/`app_secret` from the central vault (auth.py:42-53). The "no close frame" death is **two WS sessions on one account**, not REST contention. Fix = exactly one WS owner (CHECK). Retiring the server WS resolves it; approval_key issuance by CHECK does not invalidate a REST token.

**FINDING 3 — topology forces the feed through the api (mirrors 호가).**
The collector has no host port; CHECK (on the CHECK PC) reaches the api at host `:8000`. So the prices feed uses the **same two-hop path** as 호가: CHECK → api `POST /internal/check/prices` (X-Internal-Api-Key) → collector `POST /ingest/prices`. Watchlist reads go via the api proxy (`GET /api/v1/inav/watchlist`).

**FINDING 4 — snapshot dict shape (defines the wire price fields).**
`rest.snapshots` rows carry `exchange, symbol, last, base, open, high, low, volume, value, trade_time, currency, raw, error` (kis_prices.py:328-347). The engine consumes only `exchange, symbol, last, base, currency, trade_time`. `_merge_snapshot` **rejects zero/negative `last`/`base`** and **preserves prior `base`** when a new snap omits it (engine.py:256-268). `update_price_by_key` **silently drops** keys absent from `_key_to_isin` (engine.py:223-228) — the key-drift failure mode.

**FINDING 5 — day-session echo semantics (must move to CHECK).**
Today `_fetch_kis_snapshots` (main.py:354-410), during the US day window, requests `BAQ/BAY/BAA` but **echoes the response back under the original `NAS/NYS/AMS` key** (so `_key_to_isin` matches) and **pins `base` from daily bars** (never the 1-day-stale day-session base). In feed mode this whole behavior moves to CHECK: CHECK emits prices under the **server-canonical** exchange codes and supplies a **stable prev-close `base`**.

**FINDING 6 — feature-flag pattern.**
`ALLOW_TOKEN_ISSUE` (main.py:98-101) reads `os.environ.get("COLLECTOR_ALLOW_TOKEN_ISSUE","1")` at import; the value is documented and set in `docker-compose.yml` collector env (compose lines 107-134). The new price-source flag mirrors this exactly.

**FINDING 7 — state is in-memory only (coupling (c) confirmed).**
`SnapshotState` (state.py) holds everything in memory behind a lock; there is no disk last-good. A restart rebuilds from scratch, so "last-good serving" survives only within a running process. **Cold-start after a restart depends on a live feed.** Documented limitation; a disk last-good is a Phase-2 follow-up, not a Phase-1 requirement.

---

## 4. Guardrails

**Must have**
- Feature flag default = **KIS-direct** (no behavior change ships by default). Feed is opt-in per env.
- The KIS-direct code path (`_fetch_kis_snapshots`, `_ws_loop`, `_refresh_us_prev_closes`, etc.) stays **present and callable** for rollback — "retire" means "not scheduled in feed mode", never "deleted".
- `/ingest/prices` seq gate **identical** to `update_hoga` (drop `seq < stored`).
- Prices channel **separate** from the 1s 호가 channel. ETF self-price stays on the 호가 envelope (3-tick alert atomicity relies on it — main.py:604-626).
- Server keeps `resolve_instruments` / `_key_to_isin` (no live KIS) and publishes it via `/watchlist`.
- Fail-stale: stalled feed → last-good served, `price_age_s` grows, no crash.

**Must NOT have**
- No second live KIS WS session on the server while CHECK owns the WS.
- No merging price rows into the 1s 호가 payload.
- No ISIN-keyed ingest as the primary path (single source of truth = server `(exchange,symbol)` keys).
- No edits to the verbatim `kis_api/websocket_client.py` (byte-verbatim constraint — main.py:128-136).
- No touching the running process or the `:ro` legacy mounts.

---

## 5. Wire contract (the crux — two machines, two codebases)

CHECK's producer code (`kis_inav.js` / `data.js`) lives on a **separate PC / separate codebase not in this repo**. The contract below is precise enough for the CHECK side and the server side to be built independently.

### 5.1 Prices ingest — CHECK-facing endpoint (via api)

`POST http://<host>:8000/internal/check/prices`
Headers: `X-Internal-Api-Key: <INTERNAL_API_KEY>`, `Content-Type: application/json`
Body (`CheckPricesEnvelope`, identical wrapper to `CheckHogaEnvelope`):

```jsonc
{
  "schema_version": 1,
  "source": "check-agent",
  "source_timestamp": "2026-07-24T10:06:58+09:00", // when CHECK sampled the prices (ISO8601, KST ok)
  "sent_at":          "2026-07-24T10:06:58+09:00", // when CHECK sent this envelope
  "seq": 172834,                                    // monotonically increasing int; server drops seq < stored
  "payload": {
    "watchlist_version": "20260724-a1b9c3",         // the version CHECK priced against (from GET /watchlist)
    "prices": [
      {
        "exchange": "NAS",        // server-canonical KIS exchange code (as published by /watchlist); NOT BAQ/BAY/BAA
        "symbol":   "AAPL",       // uppercased; must match a /watchlist key
        "last":     227.34,       // current traded price, day-session-corrected, > 0 (drop transient zeros)
        "base":     225.10,       // stable prev-close = last COMPLETED regular-session close, > 0
        "currency": "USD",
        "trade_time": "100612",   // local HHMMSS (or ISO); stored verbatim, used for the UI "last change" stamp
        "day_session": true       // OPTIONAL, informational: this US symbol was priced off the day-session code
      }
      // … one row per priced watchlist instrument
    ]
  }
}
```

Field rules:
- `exchange`/`symbol` **must** be the server-canonical keys from `/watchlist`. Unknown keys are silently dropped by the engine (`update_price_by_key`), so wrong codes = silent unpriced components.
- `last`: only positive prices. Zeros/halts omitted (server also guards, but pre-filter).
- `base`: **stable prev-close** (last completed regular session). For US day-session symbols this is **not** the day-session TR base (1 day stale). If CHECK cannot yet compute a confident `base`, it MAY omit the field — the engine preserves the last good `base` — but on a cold server start there is no prior base, so off-hours rows stay unpriced until `base` arrives. Recommendation: **always send `base`.**
- `currency`, `trade_time`: pass-through into the engine snapshot.

Server response (mirrors `/ingest/hoga`): `{"ok": true}` on store; `{"ok": true, "ignored": "stale_seq"}` when `seq` regressed. api degrades to `503 {"detail":"collector unavailable"}` on collector-down (2s budget).

Cadence: **1–3s** recommended for the price channel. **Do NOT** piggyback the 1s 호가 channel — separate envelope, separate endpoint. Prices at 15s would still work (matches today's REST cadence) but 1–3s replaces the value the retired WS lane used to add.

### 5.2 Collector-facing endpoint (internal hop)

`POST http://collector:8100/ingest/prices` — same envelope; `state.update_prices_feed(envelope)` (seq gate). Debug read: `GET http://collector:8100/prices-feed` (mirrors `/hoga`).

### 5.3 Watchlist — what to price

`GET http://<host>:8000/api/v1/inav/watchlist` (api proxy) → collector `GET /watchlist`:

```jsonc
{
  "version": "20260724-a1b9c3",          // f(run_date, hash(sorted (exchange,symbol) set)); changes on rollover / ETF inclusion
  "generated_at": "2026-07-24 09:01:00", // KST
  "instruments": [
    { "isin": "US0378331005", "exchange": "NAS", "symbol": "AAPL", "currency": "USD" }
    // … all non-Taiwan iNAV component instruments (Phase-1 union ≈ iNAV component set)
  ]
}
```

- Built from `self.instruments` (main.py:520), filtered to exclude Taiwan (`TAIWAN_EXCHANGES`) — Taiwan stays on the server's TWSE lane (not KIS).
- `version` lets CHECK detect a daily rollover / new ETF inclusion (`_build_engine` rebuild) and re-sync its symbol set. CHECK echoes the `watchlist_version` it priced against in each envelope so the server can flag a stale-watchlist producer.
- ETag/304 pass-through via the existing `_proxy_collector` (inav.py:19) is fine.

### 5.4 CHECK-side contract obligations (behavioral spec — CHECK code is not ours)
1. Poll `/watchlist`; cache `version`; on version change, re-sync the priced symbol set within one cycle.
2. Run the **single** KIS WS session (overseas delayed ccnl) + REST snapshots (domestic + fill) to obtain `last` per instrument.
3. Perform the **US day-session remap internally** (request BAQ/BAY/BAA in the US day window) but **emit under the server-canonical exchange code** (NAS/NYS/AMS…).
4. Supply a **stable `base`** (prev regular-session close) per symbol; never the day-session TR base.
5. Emit envelopes with **monotonic `seq`**; drop transient zero prices; cadence 1–3s; separate from the 호가 channel.
6. Coverage: every non-Taiwan `/watchlist` instrument, keyed by the exact published `(exchange,symbol)`.

---

## 6. Server-side change list — Phase 1 (with file:line anchors)

> All additive and flag-gated; the KIS-direct path stays intact for rollback.

**C1. Price-source flag** — `apps/collector/collector/main.py` near line 98 (beside `ALLOW_TOKEN_ISSUE`):
`INAV_PRICE_SOURCE = os.environ.get("COLLECTOR_INAV_PRICE_SOURCE", "kis").strip().lower()` → `"kis"` (default, KIS-direct) | `"feed"`. Add `COLLECTOR_INAV_PRICE_SOURCE: "kis"` to the `docker-compose.yml` collector env block (compose ~line 116) with the same "flip to feed" doc comment style as `COLLECTOR_ALLOW_TOKEN_ISSUE`.

**C2. Feed state store** — `apps/collector/collector/state.py`, mirror the 호가 fields (state.py:113-118) and methods:
- Add `_prices_feed`, `_prices_feed_source_timestamp`, `_prices_feed_sent_at`, `_prices_feed_seq`, `_prices_feed_received_ts`, plus `_prices_feed_matched`/`_prices_feed_dropped` counters and `_watchlist_version`.
- `update_prices_feed(envelope) -> bool` — **seq gate identical to `update_hoga` (state.py:176-189)**.
- `prices_feed() -> dict` — mirror `hoga()` (state.py:286-299): payload + `inav_feed_last_received_age_s` + `inav_feed_source_age_s` + `seq`.
- Extend `_staleness_locked` (state.py:204-228) with `inav_feed_age_s`, `inav_feed_seq`, `inav_feed_matched_count`, `inav_feed_dropped_unmatched_count`, `watchlist_version`.

**C3. Ingest + debug endpoints** — `apps/collector/collector/main.py` `_build_app`, beside `/ingest/hoga` (main.py:1063-1073):
`@app.post("/ingest/prices")` → `state.update_prices_feed(envelope)` (return `{ok, ignored?}` like hoga); `@app.get("/prices-feed")` → `state.prices_feed()`.

**C4. Watchlist endpoint** — `apps/collector/collector/main.py` `_build_app`:
`@app.get("/watchlist")` returns `{version, generated_at, instruments}` from `self.instruments` minus Taiwan. Compute/store `version` in `_build_engine` (main.py:520, after instruments resolve) as `f"{run_date}-{hash(sorted keys)}"`; stash in state via a new `state.set_watchlist(version, instruments)`.

**C5. `_price_loop` body** — `apps/collector/collector/main.py:816-828`: branch on `INAV_PRICE_SOURCE`.
- `"kis"` (default): unchanged (`_fetch_kis_snapshots`).
- `"feed"`: read `state.prices_feed()`; **freshness gate** — if `inav_feed_last_received_age_s` is `None` or `≥ 15.0`, skip apply (do **not** bump `mark_price()`; let `price_age_s` grow — fail-stale, matching the 호가 15s gate at main.py:608); else extract `payload["prices"]`, call `engine.bulk_update_from_snapshots(prices)`, record matched/dropped counts (bulk returns matched count; dropped = `len(prices) - matched`), `mark_price()` when any positive `last`. In feed mode shorten the loop interval (e.g. `PRICE_REFRESH_S`→~2s) so applied prices track the push cadence.

**C6. Retire the WS lane (feed mode only)** — `apps/collector/collector/main.py` `run()` task list (main.py:1194-1205): gate `asyncio.create_task(self._ws_loop())` behind `INAV_PRICE_SOURCE == "kis"`. In feed mode the WS is simply not scheduled (code stays for rollback). `state.set_ws_connected(False)` naturally reflects the retired lane.

**C7. Seed path** — `apps/collector/collector/_build_engine` (main.py:530-541): in feed mode, skip the `_fetch_kis_snapshots` seed (or opportunistically seed from `state.prices_feed()` if an envelope already arrived). Keep the TWSE seed. The engine seeds from the first feed push.

**C8. Prev-close** — no new code: in feed mode `_refresh_us_prev_closes` (main.py:305, called only inside `_fetch_kis_snapshots`) is simply not invoked; `base` now comes from CHECK.

**C9. api service** — `apps/api`:
- `apps/api/app/schemas.py:17` — add `CheckPricesEnvelope` (identical shape to `CheckHogaEnvelope`).
- `apps/api/app/api/internal.py:44` — add `POST /internal/check/prices` forwarding to collector `/ingest/prices` (mirror `ingest_check_hoga`: X-Internal-Api-Key guard, `COLLECTOR_TIMEOUT_S=2.0`, fast 503).
- `apps/api/app/api/inav.py` — add `GET /api/v1/inav/watchlist` → `_proxy_collector("/watchlist", if_none_match)` (mirror the existing proxies).

**C10. (Optional, recommended) observability surface** — expose the C2 counters/ages in `/health` (state.health(), state.py:246) and `/snapshot.staleness` so the feed's age, seq, and match rate are visible without new infra.

Nothing in Phase 1 deletes KIS code. `_fetch_etf_quotes` (main.py:444) and WRAP stay on the server's KIS REST token in Phase 1 (they are Phase 2); FINDING 2 shows the single-WS-owner fix does not require touching REST token issuance in Phase 1.

---

## 7. Cutover & parity strategy

Feature flag default = `kis`. Flip to `feed` only after parity passes; keep `kis` for instant rollback.

**Constraint:** the WS is a **single session** — you cannot A/B two live WS sessions. So realtime-lane parity is compared via REST snapshots or a bounded shadow window, not dual-WS.

**Stage A — REST parity, server WS off (shadow window).**
Temporarily gate the server WS off (as in feed mode) but keep the server on **KIS-direct REST snapshots** (`_fetch_kis_snapshots`), while CHECK runs its WS and produces the feed to `/ingest/prices`. Over a bounded session window, compare per symbol: `|feed.last − kis_rest.last| / kis_rest.last ≤ ε` and `feed.base == kis_rest.base` (prev-close). This validates CHECK's day-session remap, base handling, and key coverage **without dual-WS**.

**Stage B — flip.**
Record a KIS-direct baseline (`/snapshot` samples). Flip `COLLECTOR_INAV_PRICE_SOURCE=feed`. Compare feed-path `/snapshot` `deviation_pct` per ETF against the recorded baseline within tolerance (e.g. ±5 bp) over the same session phase. Keep the flag reversible: flipping back to `kis` restores KIS-direct — **note the WS conflict means CHECK must stop its WS before the server WS resumes.**

**Parity metrics.**
- Per-symbol price: relative error ≤ ε (e.g. 0.1% liquid; wider for illiquid/off-hours).
- Per-symbol base equality (prev-close).
- Per-ETF `deviation_pct` feed-vs-KIS within ±5 bp.
- Key coverage: dropped-unmatched count = 0 across the window.

---

## 8. Pre-mortem (3 concrete failure scenarios)

**S1 — CHECK feed stalls mid-session** (CHECK crash / network partition).
Symptom: server keeps applying last-good prices (engine retains `_prices`); deviations silently freeze while looking live.
Mitigations: (a) freshness gate in `_price_loop` (C5) stops bumping `mark_price()` past 15s so `price_age_s`/`inav_feed_age_s` grow and the UI staleness surfaces; (b) health metric `inav_feed_age_s` + alert when > N s during an active session; (c) fail-stale, no crash (matches 호가). Cold-start caveat (FINDING 7): a **server restart during a stall** loses all in-memory prices → the server has nothing until the feed resumes; document this and consider a Phase-2 disk last-good. Auto-revert to `kis` on prolonged stall is **not** recommended (re-introduces the WS conflict) — prefer alert + manual flip after CHECK's WS is confirmed down.

**S2 — prevClose regresses to 전전일 / wrong base.**
Symptom: CHECK sends a 2-day-stale or day-session `base` → `inav_change_pct` and `deviation_pct` skew.
Mitigations: (a) contract fixes `base` = last completed regular-session close; (b) engine rejects zero base and preserves the prior good base (engine.py:256-268); (c) Stage-A parity compares `base` feed-vs-KIS per US symbol; (d) **follow-up** server sanity guard: reject a `base` that jumps > X% from the prior day's base (Phase-2, not a Phase-1 blocker).

**S3 — key-map drift: CHECK symbol codes ≠ server KIS codes** (highest-risk silent failure).
Symptom: CHECK emits `NASD`/`US`/a differently-resolved symbol; `update_price_by_key` returns None → component unpriced → `priced_weight_pct` quietly falls.
Mitigations: (a) `/watchlist` publishes the authoritative `(exchange,symbol)`; CHECK MUST price by those exact keys and echo `watchlist_version`; (b) server observability = matched vs dropped-unmatched counts per cycle (C2/C10); alert when match rate < threshold or `watchlist_version` mismatches; (c) integration test asserts a `NAS`-keyed feed row matches `_key_to_isin`.

---

## 9. Expanded test plan

**Unit**
- `update_prices_feed` seq gate: regression dropped, monotonic accepted, first-envelope accepted (mirror the 호가 seq-gate tests).
- Feed payload → engine snapshot: a `payload.prices` row maps to a dict carrying `exchange/symbol/last/base/currency/trade_time`; zero/negative `last`/`base` rejected by `_merge_snapshot`.
- Freshness gate: `inav_feed_age_s ≥ 15` ⇒ not applied and `mark_price` not bumped; `< 15` ⇒ applied.
- Watchlist version: changes when the sorted `(exchange,symbol)` set changes; stable across recompute with identical instruments.
- Day-session key echo: a feed row `exchange="NAS"` matches `_key_to_isin` built by `resolve_instruments`; a `"BAQ"` row does **not** (guards against CHECK emitting day-session codes).

**Integration**
- Golden-file parity: feed a **captured KIS snapshot set** through both paths (KIS-direct `bulk_update_from_snapshots` vs `/ingest/prices` → `_price_loop` pull → `bulk_update_from_snapshots`) and assert **identical** `/snapshot` `deviation_pct`.
- Seq gate end-to-end: api `POST /internal/check/prices` (with `X-Internal-Api-Key`) → collector `/ingest/prices`; out-of-order envelope ignored.
- Watchlist proxy: `GET /api/v1/inav/watchlist` returns the non-Taiwan instrument set with a version; 304 pass-through works.

**e2e**
- With `feed` and a recorded real CHECK session, per-ETF `deviation_pct` matches the KIS-direct baseline within ε across the session; off-hours `base_fallback` yields the same `base_nav`.
- Stall injection: stop pushes → `price_age_s`/`inav_feed_age_s` grow, last-good served, no crash; resume → recovers.

**Observability**
- `/health` + `/snapshot.staleness` expose `inav_feed_age_s`, `inav_feed_seq`, `inav_feed_matched_count`, `inav_feed_dropped_unmatched_count`, `watchlist_version`, and `ws_connected=false` (expected in feed mode).
- Alert rules: feed age > N s in-session; match rate < M%; base anomaly (S2 guard, Phase-2); `watchlist_version` mismatch.

---

## 10. Acceptance criteria (testable)

- **AC1** With `COLLECTOR_INAV_PRICE_SOURCE=feed`, the component lane issues **zero** live KIS (no WS connect, no overseas/domestic snapshot REST, no daily-bar prev-close): `ws_connected=false` and no `rest.snapshots`/`overseas_daily_bars` calls attributable to the component lane. (ETF-quotes + WRAP remain — Phase 2.)
- **AC2** `_key_to_isin` builds with **no network KIS**: an offline test with only the parquet + OpenFIGI SQLite cache present resolves instruments.
- **AC3** `GET /watchlist` returns the full non-Taiwan iNAV instrument set with `(isin,exchange,symbol,currency)` and a `version` that changes on rollover / ETF inclusion.
- **AC4** `POST /ingest/prices` seq gate drops regressions (`ignored: stale_seq`), byte-identical semantics to `/ingest/hoga`.
- **AC5** Feed-path `/snapshot` `deviation_pct` equals KIS-direct within ε across a captured session; `base`/prev-close preserved.
- **AC6** Feed stall → `price_age_s`/`inav_feed_age_s` grow, last-good served, no crash; flag flip back to `kis` restores KIS-direct (rollback works, given CHECK's WS is stopped first).
- **AC7** The 1s 호가 channel and ETF self-price atomicity are unchanged (prices not merged into the 호가 channel).
- **AC8** Default build (`kis`) is behavior-identical to today (nothing ships enabled by default).

---

## 11. Step-by-step verification

1. **Static** (done here): confirm `sync_master` is `shutil.copyfile` (no KIS API) — FINDING 1; confirm approval_key/token share the app key — FINDING 2.
2. **Default build** with `COLLECTOR_INAV_PRICE_SOURCE=kis`: diff `/snapshot` vs pre-change — identical (AC8).
3. **Unit** suite green (§9).
4. **Integration** golden-file parity green (§9) — the core equivalence proof.
5. **Stage-A shadow**: server WS off + KIS REST on; CHECK feed on; compare feed vs KIS REST per symbol + base over a window; ε met, base equality, dropped-unmatched=0.
6. **Flip** `feed` on a low-risk session; watch `/health` feed age, match rate, `watchlist_version`, and `deviation_pct` vs the recorded baseline.
7. **Sign-off**; retain the `kis` path for rollback.

---

## 12. ADR

**Decision.** Migrate the collector's realtime iNAV **component-price** lane (KIS WS delayed ticks + overseas/domestic REST snapshots + daily-bar prev-close pinning) out of the server and receive raw per-symbol prices as an HTTP **push feed** from the CHECK agent (**price-feed** schema), keeping the server's iNAV/deviation engine. Phase 1 = this lane; Phase 2 (calm window) = ETF-quote lane, WRAP, prev-close ownership, basket ownership, and the final full KIS drop.

**Drivers.** (1) Single-owner KIS WS session — resolve the approval_key "no close frame" conflict. (2) Preserve the server's recent day-session (BAQ/BAY/BAA) + prev-close-pin fixes, last-good serving, parity comparability, and the version-pinned in-container engine. (3) The server's key-mapping needs **no live KIS** (local parquet + OpenFIGI cache — FINDING 1), so the lane can fully drop live KIS while resolution stays server-side.

**Alternatives considered.**
- **Result-feed** (CHECK computes iNAV/deviation): invalidated — loses the server's recent fixes (re-implemented on a codebase we don't own), no last-good on CHECK downtime, no parity, moves the version-pinned engine off-container. (§1 Option B.)
- **ISIN-keyed ingest**: rejected as primary — duplicates the server's authoritative resolution, risks ISIN/key drift; `/watchlist` + `(exchange,symbol)` keeps a single source of truth. Kept only as a narrow fallback.
- **Split lane** (keep domestic components on server REST): deferred — leaves a server REST token issuing against the shared app key (token-ownership ambiguity); primary Phase-1 moves the whole `_fetch_kis_snapshots` output to the feed for a clean `_price_loop` replacement. Taiwan stays server-side (not KIS).

**Why chosen.** Price-feed maximizes correctness retention, rollback safety, and parity while achieving the single-WS-owner fix. FINDING 1 removes the only structural blocker to fully dropping live KIS from the lane.

**Consequences.** The server depends on CHECK for realtime component prices in-session (accepted — the "server must be 24/7 CHECK-independent" invariant was explicitly dropped by the user). In-memory state (FINDING 7) means a cold start needs a live feed. A new wire contract now spans two codebases. CHECK now owns the day-session remap and prev-close `base` correctness.

**Follow-ups.** Phase 2: ETF-quote lane, WRAP, prev-close ownership, basket ownership, full KIS token drop + token-ownership resolution. Optional: disk last-good for cold-start resilience; server-side base-anomaly guard (S2); alert rules for feed age / match rate / watchlist-version mismatch.

---

## 13. Open questions (for Architect/Critic)

- **Q1** Phase-1 domestic components: confirm CHECK will price domestic **KRX/KFO** component stocks too (the full `_fetch_kis_snapshots` output), or do we keep the split-lane sub-option A1 for Phase 1? (Affects whether the server retains any component-lane KIS REST.)
- **Q2** Token ownership in Phase 1: the server still needs a KIS REST token for ETF-quotes + WRAP (Phase 2 lanes). Confirm CHECK owning the WS does not require changing REST token issuance in Phase 1 (FINDING 2 says no), or whether we proactively move to CHECK-issued-token piggyback now.
- **Q3** Watchlist read auth: expose `/watchlist` via the public inav proxy (`/api/v1/inav/watchlist`) or under the `/internal` (X-Internal-Api-Key) router for symmetry with the POST? Recommendation: public read proxy (low sensitivity), POST stays internal.
- **Q4** Price channel cadence: 1–3s vs 15s. Recommendation 1–3s (replaces the retired WS tick value) but not on the 1s 호가 channel.
- **Q5** Disk last-good for cold-start (FINDING 7): Phase-1 nice-to-have or Phase-2 follow-up? Recommendation: Phase-2.
