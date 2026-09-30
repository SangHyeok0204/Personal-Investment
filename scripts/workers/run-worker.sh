#!/bin/bash
# 네이티브 worker 한 개를 띄운다 — LaunchAgent 가 부른다(install.sh 참고).
#
#   run-worker.sh <queue>        예) run-worker.sh sec_crawl
#
# ★왜 도커가 아니라 네이티브인가(docs/plans/…integration…md P0):
#   llm 큐는 이 맥에 로그인된 `claude` CLI 를, sec_crawl 큐의 Investing.com 크롤은
#   화면 있는 크롬을 쓴다. 둘 다 컨테이너 안에서는 닿지 않는다.
# ⚠️`--reload` 없이 돈다. API(uvicorn --reload)와 한 프로세스에 두면 코드를 고칠
#   때마다 진행 중인 백필·LLM 호출이 죽는다.
set -euo pipefail

QUEUE="${1:?queue name required (sec_crawl | llm)}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

# DB 주소는 API 와 같은 `.env.local` 에서 읽는다(환경변수가 있으면 그게 우선).
if [ -z "${DATABASE_URL:-}" ] && [ -f "$REPO/.env.local" ]; then
  DATABASE_URL="$(grep -E '^DATABASE_URL=' "$REPO/.env.local" | head -1 | cut -d= -f2-)"
fi
export DATABASE_URL
# SEC 연락처 UA(계획 A3a) — sec_crawl 수집은 이 값이 없으면 돌지 않는다.
if [ -z "${SEC_USER_AGENT:-}" ] && [ -f "$REPO/.env.local" ]; then
  # ⚠️`|| true` 필수 — 줄이 없으면 grep 이 1 을 돌려주고 `set -eo pipefail` 이 스크립트를 죽인다
  #   (실제로 두 worker 가 exit 1 로 재시작 루프에 빠졌다).
  SEC_USER_AGENT="$(grep -E '^SEC_USER_AGENT=' "$REPO/.env.local" | head -1 | cut -d= -f2- || true)"
fi
# 값에 공백·괄호가 있어 .env.local 에는 따옴표로 적는다 — 감싼 따옴표를 벗긴다.
SEC_USER_AGENT="${SEC_USER_AGENT:-}"
SEC_USER_AGENT="${SEC_USER_AGENT#\"}"; SEC_USER_AGENT="${SEC_USER_AGENT%\"}"
export SEC_USER_AGENT
export STORAGE_DIR="${STORAGE_DIR:-$REPO/storage}"
export WORKER_QUEUES="$QUEUE"
export WORKER_NAME="$QUEUE"
export PYTHONUNBUFFERED=1

cd "$REPO/apps/worker"
exec "$REPO/.venv/bin/python" main.py
