#!/bin/bash
# 대시보드(웹 next dev :3000 + API uvicorn :8000)를 껐다 켠다 — LaunchAgent com.personal-investment.dashboard-restart 가 하루 2번 부른다.
#
# ★2026-10-30 사용자 요청: "버튼 반응이 느리다 — 하루 2번 껐다 켜게". 원인 후보: next dev 가 20일째 떠서 next-server 1.07GB.
#   다시 띄운 뒤 주요 화면을 한 번씩 열어 둔다(next dev 는 화면을 처음 열 때 컴파일한다 — 안 하면 재시작 직후 첫 클릭이 느리다).
# ⚠️로그는 기존과 같은 곳(/private/tmp/pi-web-dev.log, /private/tmp/api.log)에 이어 쓴다.
set -u
REPO=/Users/adg01/Developer/Personal-Investment
WEB_LOG=/private/tmp/pi-web-dev.log
API_LOG=/private/tmp/api.log
export PATH=/Users/adg01/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

log() { echo "[restart-dashboard $(date '+%F %T')] $*"; }

stop_port() {  # 포트를 잡은 프로세스와 그 부모 체인(npm run dev / uvicorn 리로더)까지 끈다
  local port=$1 pids
  pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null)
  for p in $pids; do
    local pp; pp=$(ps -o ppid= -p "$p" | tr -d ' ')
    while [ -n "$pp" ] && [ "$pp" != 1 ] && ps -o command= -p "$pp" | grep -qE "next|npm|uvicorn"; do
      pids="$pids $pp"; pp=$(ps -o ppid= -p "$pp" | tr -d ' ')
    done
  done
  [ -z "$pids" ] && return 0
  log "port $port: kill $pids"
  kill $pids 2>/dev/null
  for _ in $(seq 1 20); do lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || return 0; sleep 1; done
  log "port $port: 아직 살아 있음 — kill -9"; kill -9 $pids 2>/dev/null; sleep 1
}

wait_http() {  # url 이 응답할 때까지(최대 secs초)
  local url=$1 secs=$2
  for _ in $(seq 1 "$secs"); do curl -s -o /dev/null -m 5 "$url" && return 0; sleep 1; done
  return 1
}

log "시작"
stop_port 3000
stop_port 8000

cd "$REPO/apps/api" || exit 1
nohup ../../.venv/bin/python -m uvicorn app.main:app --port 8000 --reload --reload-dir . --reload-dir ../worker \
  >>"$API_LOG" 2>&1 </dev/null &
cd "$REPO/apps/web" || exit 1
nohup npm run dev >>"$WEB_LOG" 2>&1 </dev/null &

wait_http http://localhost:8000/system/health 90 && log "API 응답" || log "⚠️API 가 90초 안에 응답하지 않음"
wait_http http://localhost:3000/login 120 && log "웹 응답" || log "⚠️웹이 120초 안에 응답하지 않음"

# 미리 열기 — 게이트 쿠키를 만들어 주요 화면을 한 번씩 요청한다(컴파일 데우기). 실패해도 재시작은 끝난 것.
TOKEN=$(cd "$REPO" && node -e '
const fs=require("fs"),c=require("crypto");const t=fs.readFileSync(".env","utf8");
const g=n=>(t.split("\n").find(l=>l.startsWith(n+"="))||"").slice(n.length+1).trim().replace(/^["\x27]|["\x27]$/g,"");
const exp=Math.floor(Date.now()/1000)+600;
process.stdout.write(exp+"."+c.createHmac("sha256",g("DASHBOARD_SESSION_SECRET")+":"+g("DASHBOARD_PASSWORD")).update("v1."+exp).digest("base64url"));' 2>/dev/null)
for p in / /portfolio /portfolio/holdings /research /research/market /research/earnings /macro /news/market /news/holdings \
         /strategy/entry-odds /strategy/basket-spread /strategy/dip-buy /settings/connections /data-operations; do
  curl -s -o /dev/null -m 120 -b "pi_session=$TOKEN" "http://localhost:3000$p"
done
log "끝 — 화면 미리 열기 완료"
