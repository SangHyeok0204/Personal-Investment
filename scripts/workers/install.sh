#!/bin/bash
# 네이티브 worker 를 LaunchAgent 로 설치·제거한다.
#
#   scripts/workers/install.sh            설치(이미 있으면 다시 올림)
#   scripts/workers/install.sh uninstall  제거
#   scripts/workers/install.sh status     상태
#
# ⚠️LaunchDaemon 이 아니라 **LaunchAgent**(`gui/$UID`)다. Daemon 은 로그인 세션 밖에서
#   돌아서 `claude` 의 키체인 로그인과 화면 있는 크롬에 조용히 실패한다.
# 로그: ~/Library/Logs/personal-investment/worker-<queue>.log
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/personal-investment"
QUEUES=(sec_crawl llm)
DOMAIN="gui/$(id -u)"

label() { echo "com.personal-investment.worker.$1"; }

write_plist() {
  local q="$1" plist="$AGENTS/$(label "$1").plist"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$(label "$q")</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/workers/run-worker.sh</string>
    <string>$q</string>
  </array>
  <key>RunAtLoad</key><true/>
  <!-- 죽으면 다시 띄운다. 너무 자주 죽으면 launchd 가 10초씩 쉰다. -->
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <!-- launchd 는 셸 PATH 를 물려주지 않는다. claude(npm 전역)·homebrew 를 명시. -->
    <key>PATH</key><string>$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key><string>$LOGS/worker-$q.log</string>
  <key>StandardErrorPath</key><string>$LOGS/worker-$q.log</string>
</dict>
</plist>
EOF
  echo "$plist"
}

case "${1:-install}" in
  install)
    mkdir -p "$AGENTS" "$LOGS"
    chmod +x "$REPO/scripts/workers/run-worker.sh"
    for q in "${QUEUES[@]}"; do
      plist="$(write_plist "$q")"
      launchctl bootout "$DOMAIN" "$plist" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$plist"
      echo "installed $(label "$q")"
    done
    ;;
  uninstall)
    for q in "${QUEUES[@]}"; do
      plist="$AGENTS/$(label "$q").plist"
      launchctl bootout "$DOMAIN" "$plist" 2>/dev/null || true
      rm -f "$plist"
      echo "removed $(label "$q")"
    done
    ;;
  status)
    for q in "${QUEUES[@]}"; do
      launchctl print "$DOMAIN/$(label "$q")" 2>/dev/null | grep -E "state =|pid =|last exit" || echo "$(label "$q"): not loaded"
    done
    ;;
  *) echo "usage: $0 [install|uninstall|status]" >&2; exit 2 ;;
esac
