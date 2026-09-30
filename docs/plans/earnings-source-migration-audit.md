# B7 earnings source migration integrity audit

Audit date: 2026-09-27 (Asia/Seoul). Repository: `/Users/adg01/Developer/Personal-Investment`, branch `personal-dashboard`. This is a source/static audit of the working tree, not a production acceptance test.

## Verdict

**HOLD B7 deletion under the current migration contract. Source preservation passes; functionality parity does not.** B1–B5 completion proves narrower delivery milestones, not coverage of every explicitly promised source module. The parent owns backup/deletion decisions. This audit neither deletes originals nor changes implementation, plan status, database contents, jobs or commits.

The user-provided backup was independently checked: all 55 archived files match both the manifest and retained originals by SHA-256. The earlier “only source copy” warning is now obsolete. Backup availability does not resolve the missing segment, key-metric and explicitly promised helper functionality below.

## Scope and evidence method

Read `CLAUDE.md` first. Compared the 33 Python files and two expert prompts against `docs/plans/2026-09-26-integration-13f-earnings-seasonality.md`, including plan B’s file table (lines 145–162), B1–B7 tickets (355–366), and B1–B5 completion notes (654 onward). Inspected source definitions, relevant bodies/call sites, migrated handlers, LLM/SEC/price modules, migration 0024, workbook importer, API/detail serialization, earnings page and existing tests. Searched `apps`, `database`, and `scripts` for missing symbols and corresponding concepts.

No original code was imported or executed. No live API/LLM/browser/DB call or application test suite was run: those can write caches, jobs, counters or DB records. Existing test descriptions are evidence of covered contracts, not a claim that tests passed in this audit. No independent reviewer tool was available; the final verification is a separate static consistency pass, not independent approval. Concurrent parent work is present in this dirty working tree, so B6 status is reported conservatively.

## Manifest and preservation

- Resolved Unicode source path: `/Users/adg01/Library/CloudStorage/OneDrive-개인/Ongoings/src`. Located by NFC-normalizing directory names, then used the actual filesystem spelling.
- Original tree: **88 files = 33 Python + 2 expert prompts + 20 `.omc` operational files + 33 `__pycache__` files**.
- Python: **16,683 lines**. Prompts: **111 lines** (watching 56, reaction 55), measured with `splitlines()`.
- Backup: [src.zip](../../.omc/backups/earnings-original-20260927-160259/src.zip), [manifest.json](../../.omc/backups/earnings-original-20260927-160259/manifest.json).
- Backup manifest/ZIP file-name sets agree exactly: **55 files**, excluding `__pycache__`; **33 Python + 2 prompts + 20 operational files**. Three-way SHA-256 comparison (original ↔ manifest ↔ ZIP): **55/55 match; zero mismatches**. Originals remain present.
- Backup ZIP SHA-256: `6e36e9bb47c6a8c44a0ec58b73200704fa6f9f4161df4e22f5f29d77f763826d`.
- Manifest SHA-256: `6f9d4f819043716a8f43b08e9feb1c5000bdf180f007088d20043a27d9a016ef`.
- Downloads `어닝모니터-20260926T000926Z-1-001.zip`: **4,494 file entries, 0 Python, 0 expert prompts**. Contains `input/processed/보유종목정리.xlsx`; its only `.db` entries are three `Thumbs.db` files, not `EARNINGS_MONITOR.db`. Generated issue-alert prompt text is not either source expert prompt.
- Older Downloads `어닝모니터-20260922T100836Z-1-001.zip`: **9 file entries, 2 Python** (`sync_from_original.py`, `check_server.py`), neither of the 33 audited files; **0 expert prompts**. It is not a source backup for this migration.
- The 20 `.omc` files (13 session JSON + 7 state/checkpoint/log files) are intentionally retired operational metadata, preserved in the backup. The 33 bytecode files are generated artifacts, not additional source modules; they are intentionally excluded from the source backup.

## Complete source disposition

Exactly one primary classification per source artifact. **Missing** includes partially migrated files with unresolved promised functionality; it does not mean every function is absent. **Migrated** means the in-scope core has a destination, not byte-for-byte identity. **Replaced** names a different mechanism and its limitations. **Intentionally retired** includes explicit deferrals from this migration, not authorization to destroy the archive. Proposed retirements that contradict the explicit file table remain **missing** until resolved.

| Category | Python files | Prompts | Total |
|---|---:|---:|---:|
| migrated | 3 | 0 | 3 |
| replaced | 7 | 2 | 9 |
| intentionally retired | 12 | 0 | 12 |
| missing | 11 | 0 | 11 |
| **Total** | **33** | **2** | **35** |

Paths below are relative to the repository unless explicitly named as original. `worker` abbreviates `apps/worker`; `core` denotes `apps/api/app/core`. Full source hashes are in the linked manifest.

| Original source | Lines | Classification | Destination / scope and gap evidence |
|---|---:|---|---|
| `_patch_openpyxl.py` | 25 | **replaced** | Excel rendering patch is unnecessary for the new DB/UI; workbook import uses openpyxl read-only mode. Plan explicitly permits replacement; no runtime monkeypatch equivalence claimed. |
| `alpha_vantage_client.py` | 271 | **intentionally retired** | Deferred from this migration by plan B (keyed vendor overlaps Nasdaq/Yahoo). Archived, not claimed implemented. |
| `analysis_utils.py` | 206 | **missing** | Partial: JSON extraction → worker llm/watchpoints.py:26. Optional MD&A helper (:20–27) has no equivalent. Batch parsing, DOCX creation and merge helpers belong to retired report output. G4. |
| `business_days.py` | 63 | **replaced** | Date-range/calendar handling → earnings_calendar.py and sec_sync.py; reaction.py:29 uses weekdays, not the original optional NYSE holiday calendar. Replacement is narrower; G7 acceptance caveat. |
| `central_paths.py` | 116 | **replaced** | Company S-drive/vault/legacy-mirror paths replaced by core/config.py, STORAGE_DIR and worker configuration; company mirrors intentionally omitted. |
| `company_overview.py` | 104 | **intentionally retired** | Explicitly deferred in plan. Actual source is a cached LLM company-description generator (:45,88), not simply an Alpha Vantage API helper; “needs key” does not accurately describe this file. |
| `daily_slack_summary.py` | 952 | **intentionally retired** | Slack payloads, fund/tier groupings and delivery excluded by plan. No Slack delivery migration required. |
| `daily_summaries.py` | 189 | **intentionally retired** | Four cached daily-deck summaries excluded with HTML/Slack reporting; not the optional Saturday weekly-summary promise. |
| `earnings_crawler.py` | 565 | **migrated** | Investing UI crawler/parsing → worker prices/investing.py and handlers/earnings_revenue.py; Nasdaq replaces broad calendar/EPS role. GUI/Cloudflare constraints documented in B3b. |
| `earnings_store.py` | 1548 | **replaced** | Workbook master/history/watchpoints → migration 0024, core/earnings_import.py, import_earnings_workbook.py and earnings handlers. Company sheets, report cursors/highlights/snapshots intentionally omitted. Does not establish parity with independent segment_store tables (G1/G2/G6). |
| `exhibit_parser.py` | 231 | **migrated** | Structured release extraction/validation → llm/exhibit.py and handlers/llm_exhibit.py; USD revenue gating, warnings and larger clipping window documented. This is not a replacement for segment_10q.py. |
| `export_earnings.py` | 260 | **intentionally retired** | Company-filtered Excel output excluded; personal API/UI replaces reporting purpose. |
| `format_daily_html.py` | 981 | **intentionally retired** | 16:9 daily meeting deck/share-folder output excluded. Analytical enrichment dependencies are assessed separately. |
| `format_html.py` | 1106 | **intentionally retired** | Weekly HTML, tiers and fund footnotes excluded; personal earnings page replaces presentation. |
| `format_issue_html.py` | 287 | **intentionally retired** | Issue-card report rendering excluded. Reddit/stock-issue collection is deferred, outside this src migration. |
| `format_output.py` | 1310 | **intentionally retired** | Excel template styling and combined reports excluded. |
| `import_existing_results.py` | 184 | **replaced** | Legacy results-to-master workbook bridge replaced by direct master-workbook importer. Source actually imports historical points/reactions (:62,101), not company holdings itself; only consolidated workbook coverage is established. |
| `llm_cli.py` | 73 | **replaced** | codex exec adapter → isolated claude runner llm/cli.py:109; timeout, cap and source-health errors. Explicit B2 design change. |
| `market_reaction.py` | 970 | **missing** | Partial: JSON point-result/judgment rules → llm/judgment.py + handlers/llm_judge.py. Stored key-metric comparison and full-filing actual-value recovery (:331–447) missing (G2). News/MD&A context narrowed (G4); batch report output retired. |
| `peer_signal.py` | 381 | **missing** | No same-L4/same-quarter peer evidence selection, comparable-segment qualification or direction/evidence generation in earnings runtime. Explicit promise conflicts with weekly-deck exclusion; requires scope decision (G3). |
| `post_process.py` | 7 | **intentionally retired** | Compatibility entry point for retired post_processor reporting tool. |
| `post_processor.py` | 327 | **intentionally retired** | Highlight selection, MDA-enhanced report regeneration and selected-ticker HTML output excluded with team reporting. |
| `report_reaction_display.py` | 243 | **missing** | Report-only compact/highlight reaction formatting (:204–243) not ported; earnings page displays reaction_note/points but does not implement these formatting rules. Likely retirement candidate, but plan explicitly promises migration; unresolved G5. |
| `run_pipeline.py` | 2235 | **missing** | Partial decomposition → sec_sync.py + earnings_calendar/revenue/result + LLM handlers/queue registry. Daily-server and meeting generation retired; segment/key-metric/peer stages not ported (G1–G3), recovery differs (G8). |
| `sec_edgar.py` | 681 | **missing** | Partial: SEC client + Ex.99.1/6-K path → sec/client.py, sec/exhibit.py. Original filename/size/primary-document fallbacks absent (G8); optional 10-Q MD&A absent (G4). |
| `segment_10q.py` | 388 | **missing** | No deterministic 10-Q/10-K R-file segment table parser, matching-period selection, direct YoY calculation or single-segment fallback found. G1. |
| `segment_desc.py` | 69 | **missing** | No cached segment-description generator/store. Explicitly promised despite original deck usage. G1/G5. |
| `segment_store.py` | 758 | **missing** | Partial: guidance/watchpoint/result records replaced by 0024 tables and result-detail JSON. Segment history/aliases/tags, description cache, key_metrics and cold-start reconciliation absent. G1/G2/G6. |
| `stock_returns.py` | 470 | **missing** | Fixed-session Toss reaction exists, but this file calculates announcement-to-today, weekly/monthly close returns and market cap for weekly reports (:130–224). Not equivalent to reaction.py. Explicit file-table promise conflicts with reporting retirement (G5). |
| `toss_prices.py` | 285 | **migrated** | AMC/BMO fixed-window minute-bar reaction → prices/reaction.py, using existing TossPriceSource. Timing-unknown NULL and wall-clock end checks retained; holiday handling narrower (G7). |
| `update_holdings.py` | 285 | **intentionally retired** | Company M2205/fund workbook updates excluded; target universe comes from personal current_positions + watchlist. |
| `watching_points.py` | 989 | **missing** | Partial: JSON ≤4 points and D-3 jobs migrated. Segment tags/key metric discarded from domain persistence, no previous-segment lookup (G1/G2); preview-news/MD&A input narrowed (G4). Weekly batch summaries retired. |
| `web_fallback.py` | 124 | **replaced** | Only CLI invocation centralized; web-search earnings fallback NOT ported. B2 completion notes explicitly retire it in favor of Nasdaq/SEC/Investing and tools-disabled LLM. Label is replacement of role, not full functional migration; G4. |
| `prompts/market_reaction_expert.md` | 55 | **replaced** | Korean point-result/narrative rules partly represented by llm/judgment.py. Original DETAIL/SUMMARIES/OVERALL multi-company report contract and news-driven analysis not reproduced; report contract retired, evidence narrowed per B5. |
| `prompts/watching_points_expert.md` | 56 | **replaced** | Core ≤4 Korean watchpoint rules represented by llm/watchpoints.py. Original five-section preview, DETAIL/SUMMARIES/OVERALL report and latest-news priority are not full equivalents; report output retired, context reduction G4. |

## Gaps and deletion gates

### G1 — Promised segment pipeline is only partially present (blocking)

Original `segment_10q.py:308` reads 10-Q/10-K R-file segment disclosures, matches filings to announcement dates, derives YoY from current/prior columns and supports single-segment businesses. `run_pipeline.py:1315` explicitly prefers this deterministic source over LLM press-release segments; `:420` uses prior/current segments and descriptions for enrichment. `segment_store.py:292`, `:437`, `:475`, `:520` normalize aliases, reconcile cold-start tags and retrieve segment history. `segment_desc.py:58` caches descriptions.

The destination `apps/worker/handlers/llm_exhibit.py:45` stores release-derived segments in `earnings_results.detail`. That is real partial migration, but no 10-Q segment parser, normalized history/tag lifecycle or description cache was found. `apps/api/app/api/earnings_monitor.py:101` reads `r.detail` but serializes only its overall verdict, not segment records; the earnings page has no segment-history display. Parsing some release segments does not cover the explicitly promised `segment_10q.py`/`segment_store.py`/`segment_desc.py` group.

**Gate:** implement and verify the retained segment responsibilities, or explicitly amend the scope to release-only segments and retire the rest. Report-only descriptions can reasonably be retired, but that must reconcile the file table rather than silently treating them as migrated.

### G2 — Key metric and watchpoint segment identity are lost (blocking)

Original `watching_points.py:148` returns key metric name/threshold/unit plus tags; `run_pipeline.py:1566` persists them with `upsert_key_metric`/`upsert_watchpoints`. `market_reaction.py:331` extracts the actual metric from up to 60,000 characters of filing text and stores actual/met; `:379` supplies the previously chosen metric to judgment. `run_pipeline.py:1696` retries missing actual values even after reaction prose has already been filled.

Destination `apps/worker/llm/watchpoints.py:81` still parses `segment` and `key_metric`. But `handlers/llm_watchpoints.py:45` stores only point text/model/source, and `:90` merely returns key_metric/detail in the job result. Migration `0024_earnings.py:88` has no segment-tag fields; no earnings key-metric persistence/lookup was found. Job output is not a domain data path: `handlers/llm_judge.py` does not retrieve the selected metric/threshold, and its prompt has no such arguments. A generic `verdicts.key_metric` label does not restore that comparison.

**Gate:** retain metric identity/threshold/unit and segment tags through storage → result extraction → judgment/API, or explicitly remove this promised behavior. A successful LLM parse or NVDA round-trip in B2 is insufficient evidence of persistence.

### G3 — Peer signal explicitly promised but absent (blocking scope conflict)

Original `peer_signal.py:223`/`:282` selects already-reported same-quarter peers in the same L4 classification, qualifies comparable businesses/segments, and produces direction plus evidence. It depends on local industry classification and broader peer history. `run_pipeline.py:550` shows that its caller is deliberately enabled for the weekly deck only.

Thus it is **both a real analytical module and originally team-report-specific**. Plan B excludes weekly meeting slides yet explicitly adds `peer_signal.py` to the migration list at line 159. No earnings peer-selection/evidence pipeline was found; unrelated value-chain classifications do not establish integration. Personal holdings-only ingestion also does not provide the original peer evidence universe.

**Gate:** explicitly retire peer analysis with the weekly deck, or define a public/personal peer universe and implement the analysis. Do not import company fund memberships to satisfy it.

### G4 — Four-helper promise and narrowed LLM evidence (mixed disposition)

- **`analysis_utils.py`: partial.** JSON extraction has a replacement; the optional MD&A path (`:20–27` → original `sec_edgar.get_mda_text`) does not. DOCX, batch report parsing and analysis-file merging are report-output responsibilities and can retire with those reports. The umbrella “954 lines migrated” claim cannot stand without this split.
- **`web_fallback.py`: deliberate replacement, not parity.** It previously used an opt-in web-search fallback for EPS/revenue/IR text. B2 completion notes explicitly discard that behavior, and `llm/cli.py:1` documents the same choice. Shared invocation and public collectors replace the role; no web fallback exists. This is a documented narrowing, not a newly discovered missing implementation requiring restoration.
- Original `watching_points.py:167` supplies preview headlines, optional MD&A and previous segments. Destination `llm_watchpoints.run` supplies only the most recent release; although `build_prompt` accepts headlines, the handler never provides them. B2 documents the context change. Original `market_reaction.py` also retrieved news articles; B5 explicitly narrows judgment to release/segment/guidance evidence. Tools-disabled LLM execution does not technically preclude application-side news collection, but the later completion notes choose the narrower design.
- Both expert Markdown prompts are archived. The running JSON prompts preserve selected rules, not the original multi-company detailed-report contracts. Do not claim the files or their complete analysis contracts were migrated verbatim.

**Gate:** reconcile the explicit `analysis_utils`/MD&A promise with the documented context reduction. No need to restore retired DOCX/batch output or the expressly discarded LLM web-search behavior.

### G5 — Report-only helpers listed as migration targets need explicit retirement (blocking scope reconciliation)

`report_reaction_display.py` is explicitly “Report-only Last Week reaction display formatting”; it applies highlights, separate length budgets and compact metric labels. The new page's reaction_note/watchpoint presentation is not the same formatter. This is an excellent retirement candidate, but the later explicit file table says migrate it.

`stock_returns.py` is weekly-report close-to-close return calculation, including announcement-to-today, week and month periods. `toss_prices.py` is a different calculation: fixed AMC/BMO minute-bar reaction. Porting the latter cannot prove the former migrated. Company overview was expressly deferred; segment descriptions were expressly promised and therefore require a separate disposition.

**Gate:** record a file-specific retirement decision for report formatting/longer-period returns/descriptions, or implement the promised subset. Do not rebuild company decks, Slack or fund reporting merely to make file counts look complete. The optional Saturday 09:00 weekly LLM summary has no identified job; being marked optional in the plan, it is a scope note rather than a mandatory deletion blocker by itself.

### G6 — “Workbook source means no DB loss” is not established (data scope gate)

The parent has corrected the plan’s false ZIP/DB claim; `EARNINGS_MONITOR.db` is absent from the Downloads ZIP. That documentation correction is complete and is not a remaining B7 task. B1 completion notes also acknowledge the absence. But their “잃는 것 없음” conclusion overextends `earnings_store.mirror_master_to_db`.

Original `earnings_store.py:525` mirrors only `holdings_master`, `holdings_history`, and `holdings_funds`. Separately, `segment_store.py:36` defines `quarterly_results`, `segments`, `guidance`, `watchpoints` with segment tags, `segment_descriptions`, `pending_retries`, `key_metrics`, and `verdicts`; these are populated by analysis stages, not wholly reconstructed by those three workbook mirrors. Company description caching adds another separately managed field. The destination workbook parser only handles current/history and watchpoint sheets, and migration 0024 contains no importer for those independent original analytical tables.

This proves **unverified historical coverage**, not that a known number of rows was lost: the actual original analytical DB was not available here. The backup verified above preserves source and prompts, **not that missing DB**. B1's logged 19 events/results and 70 watchpoints remain reported execution evidence, not independently re-counted production rows.

**Gate:** parent records whether analytical history must be recovered from the original DB, regenerated from public filings, or explicitly waived. Keep source preservation separate from data preservation; do not claim the verified source ZIP solves unavailable analytical history.

### G7 — Calendar replacement is narrower (verification/scope caveat)

Original `business_days.py:24` optionally uses NYSE holidays; original Toss logic calls its US-business-day helper. Destination `prices/reaction.py:29` uses weekdays only and relies on prior available bars for a holiday baseline. This may still yield the correct previous close, so it is not evidence of an observed wrong return. Existing tests cover a Monday/Friday weekend case, not holiday parity. Korean report-generation holiday guards are intentionally obsolete.

**Gate:** document/verify US-holiday baseline behavior before claiming business-day equivalence, or explicitly accept the narrower replacement. Do not classify omitted Korean deck scheduling as a personal-monitor gap.

### G8 — SEC fallback and recovery stages not fully ported (blocking for full stage parity)

Original `sec_edgar.py:325` supports filename-pattern/size/primary-document fallback when typed exhibit discovery fails. Destination `sec/exhibit.py:176` tries typed EX-99 documents and immediately continues when none is found. Its introductory comment still mentions filename/size fallback, but the executed function does not implement it. This is a concrete gap in a promised source module, separate from the intentional filing-date matching fixes recorded in B4/B5.

Recovery also differs: `handlers/earnings_result.py:collect` sets the filing URL and queues `LLM_EXHIBIT` once per event/accession, with no status filter in that deduplication query. Later candidate scans target missing filing/reaction, not missing structured output. `llm_exhibit.py` queues `LLM_JUDGE` only during exhibit processing, and `llm_watchpoints.py` has no downstream judgment scheduling when points arrive later. Thus a failed extraction after the URL was stored, or points arriving after exhibit completion, lacks an evident automatic domain catch-up path. The original pipeline's pending-result and missing-key-metric passes were not equivalent to this one-shot chain. This is a static recovery finding, not a reproduced production outage; generic/manual job recovery may be possible.

**Gate:** port/verify necessary fallback and missed-stage catch-up, or explicitly narrow the recovery contract. At minimum test failed-exhibit reprocessing and points-created-after-exhibit ordering. The documented deliberate retirement of `web_fallback` does not retire all non-LLM SEC fallback/retry behavior.

## What is already covered, and what is deliberately out

Calendar/EPS collection, daily Investing revenue collection, common SEC access, basic release extraction, next-quarter revenue/EPS guidance, fixed-window Toss reaction, isolated Claude execution, D-3 points and point-result judgments all have identifiable implementation destinations. Relevant tests are in `apps/worker/tests/test_earnings_calendar.py`, `test_investing.py`, `test_llm.py`, `test_earnings_result.py`, `test_llm_judgment.py`, and API `test_earnings_import.py`/`test_earnings_monitor.py`. These tests do not establish the absent segment-history, key-metric or peer workflows.

Company fund holdings, S-drive mirrors, Excel/HTML meeting decks, Slack delivery, manual report highlights and report exports are intentionally excluded. Alpha Vantage and company overview are deferred. Reddit issue monitoring is a separate later phase. Those omissions do not require implementation to satisfy the personal-monitor scope.

B6 is a separate B7 prerequisite. The earnings page/API exist; parent work changed legacy proxy/component files during this audit. This report does not certify B6 routing cleanup or visual acceptance, and a B6 pass would not close G1–G8.

## Parent handoff

1. Source preservation: **verified**, no further backup requested by this audit.
2. Source inventory: **35/35 source artifacts classified**, plus generated/operational files accounted for.
3. Resolve G1/G2/G3 and the explicit helper/report scope conflicts; address SEC fallback/recovery or record a narrower contract. Record G6 historical-data disposition and G7 calendar acceptance evidence.
4. Confirm B6 independently. Update the migration ledger to match accepted scope and evidence; do not mark B7 complete solely because this report and a backup exist.
5. Parent alone handles any eventual original-source deletion. **No deletion or commit performed by this audit.**

Final static verification: the 35 table entries exactly match the manifest’s 33 Python files and two prompts, with no duplicates or omissions; individual line counts agree. All 55 retained original files still match manifest hashes after report creation. Only this report was written by this audit.
