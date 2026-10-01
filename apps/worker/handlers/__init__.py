from . import csv_import, cusip_resolve, earnings_calendar, earnings_result, earnings_revenue, llm_exhibit, llm_judge, llm_watchpoints, plaud_video, seasonality_append, sec_collect, sync_kiwoom_portfolio, test_job

HANDLERS = {
    "TEST_JOB": test_job.run,
    "CSV_IMPORT": csv_import.run,
    "SYNC_KIWOOM_PORTFOLIO": sync_kiwoom_portfolio.run,
    "SEASONALITY_APPEND": seasonality_append.run,  # 큐 sec_crawl
    "SEC_13F": sec_collect.run_13f,  # 큐 sec_crawl (계획 A3b)
    "SEC_FORM4": sec_collect.run_form4,
    "SEC_13DG": sec_collect.run_13dg,
    "SEC_13F_BACKFILL": sec_collect.run_backfill,  # 계획 A7 — 새 거장 SEC 직접 백필
    "CUSIP_RESOLVE": cusip_resolve.run,  # 큐 sec_crawl (계획 A4)
    "EARNINGS_CALENDAR": earnings_calendar.run,  # 큐 sec_crawl (계획 B3a)
    "EARNINGS_REVENUE": earnings_revenue.run,  # 큐 sec_crawl — 화면 있는 크롬 (계획 B3b)
    "EARNINGS_RESULT": earnings_result.run,  # 큐 sec_crawl (계획 B4)
    "LLM_EXHIBIT": llm_exhibit.run,  # 큐 llm (계획 B4)
    "LLM_JUDGE": llm_judge.run,  # 큐 llm (계획 B5)
    "LLM_WATCHPOINTS": llm_watchpoints.run,  # 큐 llm (계획 B2 · B5)
    "PLAUD_VIDEO": plaud_video.run,  # 큐 llm — Plaud 유튜브 녹음 한 문단 요약(/news/video)
}
