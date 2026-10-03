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

# ★(M2) `.env.local` 에서 허용된 키만 export 한다 — 키마다 블록을 늘리다 빠뜨리는 일을 막는다.
#   허용: LLM_* · WORKER_* · SEC_USER_AGENT · DATABASE_URL · PLAUD_*. 이미 환경에 있으면 그게 우선.
#   감싼 따옴표("…" / '…')는 벗긴다(SEC UA 처럼 공백·괄호가 든 값). 값은 절대 출력하지 않는다.
load_env_local() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  # ⚠️`|| true` 필수 — 맞는 줄이 없으면 grep 이 1 을 돌려주고 `set -eo pipefail` 이 스크립트를 죽인다
  #   (실제로 두 worker 가 exit 1 로 재시작 루프에 빠졌다).
  while IFS= read -r line; do
    key="${line%%=*}"
    val="${line#*=}"
    [ -n "${!key+x}" ] && continue
    if [[ "$val" == \"*\" && ${#val} -ge 2 ]] || [[ "$val" == \'*\' && ${#val} -ge 2 ]]; then
      val="${val:1:${#val}-2}"
    fi
    export "$key=$val"
  done < <(grep -E '^(LLM_[A-Za-z0-9_]*|WORKER_[A-Za-z0-9_]*|SEC_USER_AGENT|DATABASE_URL|PLAUD_[A-Za-z0-9_]*)=' "$file" || true)
}

# 테스트에서 함수만 불러 쓸 수 있게(`RUN_WORKER_SOURCE_ONLY=1 source run-worker.sh`).
if [ "${RUN_WORKER_SOURCE_ONLY:-}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

QUEUE="${1:?queue name required (sec_crawl | llm)}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

# DB 주소·SEC UA·LLM 상한 등은 API 와 같은 `.env.local` 에서 읽는다.
load_env_local "$REPO/.env.local"
export STORAGE_DIR="${STORAGE_DIR:-$REPO/storage}"
export WORKER_QUEUES="$QUEUE"
export WORKER_NAME="$QUEUE"
export PYTHONUNBUFFERED=1

cd "$REPO/apps/worker"
exec "$REPO/.venv/bin/python" main.py
