# Open Questions

## CHECK-agent KIS Consolidation (iNAV price-feed) - 2026-07-24
- [x] Phase-1 domestic components: does CHECK price KRX/KFO component stocks too (full `_fetch_kis_snapshots` output), or keep split-lane sub-option A1 for Phase 1? — Decides whether the server retains any component-lane KIS REST. — iNAV 제거로 해당 없음 (2026-09-30, personal-dashboard-scope)
- [x] Token ownership in Phase 1: server still needs a KIS REST token for ETF-quotes + WRAP (Phase 2 lanes). Confirm CHECK owning the WS needs no REST-token change now (FINDING 2 says no), or proactively move to CHECK-issued-token piggyback. — Avoids dual token issuance against the shared app key. — iNAV 제거로 해당 없음 (2026-09-30, personal-dashboard-scope)
- [x] Watchlist read auth: public inav proxy (`/api/v1/inav/watchlist`) vs `/internal` X-Internal-Api-Key router. — Recommendation: public read, POST stays internal. — iNAV 제거로 해당 없음 (2026-09-30, personal-dashboard-scope)
- [x] Price channel cadence: 1-3s vs 15s (must stay off the 1s hoga channel). — Recommendation: 1-3s. — iNAV 제거로 해당 없음 (2026-09-30, personal-dashboard-scope)
- [x] Disk last-good for cold-start (state is in-memory only): Phase-1 nice-to-have or Phase-2 follow-up? — Recommendation: Phase-2. — iNAV 제거로 해당 없음 (2026-09-30, personal-dashboard-scope)

## Personal Dashboard Scope - still open (2026-09-30)
- [ ] Q3: AC-4 judged by host run only (default taken). Docker boot repair (step 3.4: `config.py` parents guard + api Dockerfile copies worker) not done — api Docker image stays broken until then.
- [ ] Q4: `/stock-discussion` and its `sd_*` tables (`sd_etf_meta`, `sd_posts`, `sd_author_labels`, `sd_sync_state`) left untouched — decide removal.
- [ ] Q5: `workflows/n8n/weekly-report-daily.json` (Windows trigger file drop) still present — out of scope, decide removal.
- [ ] Q6: `RESEARCH_DIR=<repo>/storage/research` set in `.env`/`.env.local` (gitignored `storage/research/*`); user must put at least one document there, else `/research` library shows its setup hint (AC-5 allow-list).
- [ ] Q7: `ge-*` design tokens (`bg-ge-header`, `text-ge-point`) and "GE 하우스 스타일" in `DESIGN.md` name the company brand — follow-up rename.
- [ ] ADR: **repo is public; consider private/history rewrite before any push** (e.g. `git filter-repo`) — past commits still hold company drive paths, vault location, LAN IPs and the old collector code.
- [ ] ADR: n8n `perf-report-daily` workflow — deactivate inside n8n (`n8n list:workflow` → `n8n update:workflow --id=<id> --active=false`); Docker was not running at Phase 3.
- [ ] ADR: a real rebalance screen on the kept backend (`rebalance_targets`).
- [ ] ADR: optional SEC 424B-based hyperscaler bond tracker as a free 금리(1) replacement.
