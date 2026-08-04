# Open Questions

## CHECK-agent KIS Consolidation (iNAV price-feed) - 2026-07-24
- [ ] Phase-1 domestic components: does CHECK price KRX/KFO component stocks too (full `_fetch_kis_snapshots` output), or keep split-lane sub-option A1 for Phase 1? — Decides whether the server retains any component-lane KIS REST.
- [ ] Token ownership in Phase 1: server still needs a KIS REST token for ETF-quotes + WRAP (Phase 2 lanes). Confirm CHECK owning the WS needs no REST-token change now (FINDING 2 says no), or proactively move to CHECK-issued-token piggyback. — Avoids dual token issuance against the shared app key.
- [ ] Watchlist read auth: public inav proxy (`/api/v1/inav/watchlist`) vs `/internal` X-Internal-Api-Key router. — Recommendation: public read, POST stays internal.
- [ ] Price channel cadence: 1-3s vs 15s (must stay off the 1s hoga channel). — Recommendation: 1-3s.
- [ ] Disk last-good for cold-start (state is in-memory only): Phase-1 nice-to-have or Phase-2 follow-up? — Recommendation: Phase-2.
