from . import csv_import, test_job

HANDLERS = {
    "TEST_JOB": test_job.run,
    "CSV_IMPORT": csv_import.run,
}
