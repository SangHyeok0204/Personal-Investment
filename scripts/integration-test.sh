#!/usr/bin/env bash
#
# End-to-end integration test for the personal investment platform.
# Verifies: health -> create job -> worker processes -> SUCCESS, for the
# test job, CSV import, and internal (n8n) job paths, then checks stats.
#
# Run from the repository root:  bash scripts/integration-test.sh
# Override the target with:      API_BASE_URL=http://host:port bash scripts/integration-test.sh
set -euo pipefail

BASE="${API_BASE_URL:-http://localhost:8000}"

trap 'echo "FAIL: integration test aborted (command failed with exit $?)" >&2; exit 1' ERR

# Poll a job until it reaches SUCCESS. Fail fast on FAILED or after ~40s.
poll_job() {
  local job_id="$1" label="$2"
  local body status error
  for _ in $(seq 1 20); do
    body="$(curl -fsS "$BASE/api/v1/jobs/$job_id")"
    status="$(printf '%s' "$body" | jq -r '.status')"
    if [ "$status" = "SUCCESS" ]; then
      echo "PASS: $label reached SUCCESS (job $job_id)"
      return 0
    fi
    if [ "$status" = "FAILED" ]; then
      error="$(printf '%s' "$body" | jq -r '.error_message // "unknown error"')"
      echo "FAIL: $label job $job_id FAILED: $error"
      exit 1
    fi
    sleep 2
  done
  echo "FAIL: $label job $job_id did not reach SUCCESS within 40s (last status: ${status:-none})"
  exit 1
}

echo "Integration test against $BASE"

# 1. Health check: database must be connected.
health="$(curl -fsS "$BASE/system/health")"
db="$(printf '%s' "$health" | jq -r '.database')"
if [ "$db" = "connected" ]; then
  echo "PASS: /system/health database=connected"
else
  echo "FAIL: /system/health database=$db"
  exit 1
fi

# 2. Test job: create and wait for the worker to finish it.
test_job_id="$(curl -fsS -X POST "$BASE/api/v1/jobs/test" -H 'Content-Type: application/json' -d '{}' | jq -r '.id')"
if [ -z "$test_job_id" ] || [ "$test_job_id" = "null" ]; then
  echo "FAIL: POST /api/v1/jobs/test did not return an id"
  exit 1
fi
echo "PASS: created test job $test_job_id"
poll_job "$test_job_id" "test job"

# 3. CSV import: upload the sample file and wait for processing.
csv_job_id="$(curl -fsS -X POST "$BASE/api/v1/imports/csv" -F "file=@scripts/sample-holdings.csv" | jq -r '.job_id')"
if [ -z "$csv_job_id" ] || [ "$csv_job_id" = "null" ]; then
  echo "FAIL: POST /api/v1/imports/csv did not return a job_id"
  exit 1
fi
echo "PASS: created CSV import job $csv_job_id"
poll_job "$csv_job_id" "CSV import job"

# 4. Internal job: the path n8n uses.
internal_job_id="$(curl -fsS -X POST "$BASE/internal/jobs" -H 'Content-Type: application/json' -d '{"job_type":"TEST_JOB","payload":{"source":"integration-test"}}' | jq -r '.id')"
if [ -z "$internal_job_id" ] || [ "$internal_job_id" = "null" ]; then
  echo "FAIL: POST /internal/jobs did not return an id"
  exit 1
fi
echo "PASS: created internal job $internal_job_id"
poll_job "$internal_job_id" "internal job"

# 5. Stats: at least the three jobs above must have succeeded.
success_count="$(curl -fsS "$BASE/api/v1/jobs/stats" | jq -r '.success')"
if [ "$success_count" -ge 3 ] 2>/dev/null; then
  echo "PASS: /api/v1/jobs/stats success=$success_count (>= 3)"
else
  echo "FAIL: /api/v1/jobs/stats success=$success_count (expected >= 3)"
  exit 1
fi

echo "ALL INTEGRATION TESTS PASSED"
