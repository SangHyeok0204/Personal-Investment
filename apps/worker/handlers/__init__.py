from . import csv_import, sync_kiwoom_portfolio, test_job

HANDLERS = {
    "TEST_JOB": test_job.run,
    "CSV_IMPORT": csv_import.run,
    "SYNC_KIWOOM_PORTFOLIO": sync_kiwoom_portfolio.run,
}
