#!/usr/bin/env bash
#
# End-to-end integration test for the personal investment platform.
# Verifies: health -> create job -> worker processes -> SUCCESS, for the
# test job, CSV import, and internal (n8n) job paths, then checks stats.
# Also verifies the Kiwoom pre-keys E2E: brokerage-connections list,
# portfolio overview, a sync job that fails cleanly without keys (or
# succeeds when keys are set), and that /internal rejects calls missing the
# X-Internal-API-Key header (401).
#
# Run from the repository root:  bash scripts/integration-test.sh
# Override the target with:      API_BASE_URL=http://host:port bash scripts/integration-test.sh
# INTERNAL_API_KEY is taken from the environment or .env (default from .env.example).
set -euo pipefail

BASE="${API_BASE_URL:-http://localhost:8000}"

# INTERNAL_API_KEY authenticates calls to the /internal router. Prefer an
# already-exported value; otherwise read it from .env at the repo root (robust
# to comments and surrounding whitespace); finally fall back to the default
# shipped in .env.example so a fresh checkout still runs.
INTERNAL_API_KEY="${INTERNAL_API_KEY:-}"
if [ -z "$INTERNAL_API_KEY" ] && [ -f .env ]; then
  INTERNAL_API_KEY="$(grep -E '^[[:space:]]*INTERNAL_API_KEY=' .env | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
fi
INTERNAL_API_KEY="${INTERNAL_API_KEY:-change_me_internal}"

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

# Poll a job until it reaches a terminal state (SUCCESS or FAILED). Prints
# "<status><TAB><error_message>" to stdout and returns 0; unlike poll_job it
# does not treat FAILED as a script failure -- the caller decides. Times out
# after ~40s.
poll_job_terminal() {
  local job_id="$1" label="$2"
  local body status error
  for _ in $(seq 1 20); do
    body="$(curl -fsS "$BASE/api/v1/jobs/$job_id")"
    status="$(printf '%s' "$body" | jq -r '.status')"
    if [ "$status" = "SUCCESS" ] || [ "$status" = "FAILED" ]; then
      error="$(printf '%s' "$body" | jq -r '.error_message // ""')"
      printf '%s\t%s\n' "$status" "$error"
      return 0
    fi
    sleep 2
  done
  echo "FAIL: $label job $job_id did not reach a terminal state within 40s (last status: ${status:-none})" >&2
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

# 4. Internal job: the path n8n uses (now requires the X-Internal-API-Key header).
internal_job_id="$(curl -fsS -X POST "$BASE/internal/jobs" -H 'Content-Type: application/json' -H "X-Internal-API-Key: $INTERNAL_API_KEY" -d '{"job_type":"TEST_JOB","payload":{"source":"integration-test"}}' | jq -r '.id')"
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

# 6. Kiwoom: brokerage connections list. Exactly one seeded connection, and the
#    credentials_configured field must be present (false is fine before keys).
connections="$(curl -fsS "$BASE/api/v1/brokerage-connections")"
conn_count="$(printf '%s' "$connections" | jq -r '.items | length')"
if [ "$conn_count" != "1" ]; then
  echo "FAIL: /api/v1/brokerage-connections returned $conn_count items (expected 1)"
  exit 1
fi
if [ "$(printf '%s' "$connections" | jq -r '.items[0] | has("credentials_configured")')" != "true" ]; then
  echo "FAIL: /api/v1/brokerage-connections item missing credentials_configured field"
  exit 1
fi
connection_id="$(printf '%s' "$connections" | jq -r '.items[0].id')"
cred_configured="$(printf '%s' "$connections" | jq -r '.items[0].credentials_configured')"
echo "PASS: /api/v1/brokerage-connections has 1 item (credentials_configured=$cred_configured, id=$connection_id)"

# 7. Kiwoom: portfolio overview responds 200 with a sync_status field even when
#    the DB is empty (zeros/empty arrays, never 404).
overview="$(curl -fsS "$BASE/api/v1/portfolio/overview")"
if [ "$(printf '%s' "$overview" | jq -r 'has("sync_status")')" = "true" ]; then
  echo "PASS: /api/v1/portfolio/overview has sync_status ($(printf '%s' "$overview" | jq -r '.sync_status'))"
else
  echo "FAIL: /api/v1/portfolio/overview missing sync_status field"
  exit 1
fi

# 8. Kiwoom: trigger a sync for the seeded connection and wait for a terminal
#    state. Without keys the worker must FAIL cleanly at validate_configuration
#    ("... is not configured"); with keys configured, SUCCESS is also a pass.
sync_job_id="$(curl -fsS -X POST "$BASE/api/v1/brokerage-connections/$connection_id/sync" | jq -r '.job_id')"
if [ -z "$sync_job_id" ] || [ "$sync_job_id" = "null" ]; then
  echo "FAIL: POST /api/v1/brokerage-connections/$connection_id/sync did not return a job_id"
  exit 1
fi
echo "PASS: created kiwoom sync job $sync_job_id"
sync_result="$(poll_job_terminal "$sync_job_id" "kiwoom sync")"
sync_status="$(printf '%s' "$sync_result" | cut -f1)"
sync_error="$(printf '%s' "$sync_result" | cut -f2-)"
if [ "$sync_status" = "FAILED" ]; then
  case "$sync_error" in
    *"not configured"*|*"not_configured"*)
      echo "PASS: sync fails cleanly without keys (job $sync_job_id: $sync_error)"
      ;;
    *)
      echo "FAIL: kiwoom sync job $sync_job_id FAILED but not due to missing keys: $sync_error"
      exit 1
      ;;
  esac
elif [ "$sync_status" = "SUCCESS" ]; then
  echo "PASS: sync succeeded with configured keys (job $sync_job_id)"
else
  echo "FAIL: kiwoom sync job $sync_job_id reached unexpected status: ${sync_status:-none}"
  exit 1
fi

# 9. Internal auth: /internal/jobs without the X-Internal-API-Key header must be
#    rejected with 401 (no -f here so curl does not abort on the HTTP error).
unauth_code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/internal/jobs" -H 'Content-Type: application/json' -d '{"job_type":"TEST_JOB","payload":{"source":"no-auth"}}')"
if [ "$unauth_code" = "401" ]; then
  echo "PASS: /internal/jobs without header rejected (401)"
else
  echo "FAIL: /internal/jobs without header returned $unauth_code (expected 401)"
  exit 1
fi

echo "ALL INTEGRATION TESTS PASSED"
