#!/usr/bin/env bash
# PreToolUse 권한 가드 — bypass 모드에서도 실제로 막는 층.
# 네트워크 없음, 50ms 이내. OMC 전역 훅과 나란히 돈다.
#   deny  → stderr 에 이유, exit 2
#   ask   → hookSpecificOutput JSON, exit 0
#   그 외 → exit 0 (통과)
set -u

input=$(cat)
tool=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
fp=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

deny() { echo "guard: 차단 — $1" >&2; exit 2; }
ask() {
  jq -cn --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'
  exit 0
}

# 명령 경계: 문자열 시작 또는 ; & | ( ` 공백(줄바꿈 포함) 뒤
B='(^|[;&|(`[:space:]])'
# .env* 파일 참조 (경로 앞부분 허용)
ENV='(^|[[:space:]/"'"'"'=<])\.env[^/[:space:]"'"'"';|&)]*'

case "$tool" in
  Read|Edit|Write)
    # .env* 내용은 도구로 읽거나 고치지 않는다
    [[ "$fp" =~ (^|/)\.env[^/]*$ ]] && deny "$tool 로 .env* 접근 금지 ($fp)"
    ;;
  Bash)
    [[ "$cmd" =~ ${B}git[[:space:]]+reset[[:space:]]+--hard ]] && deny "git reset --hard"
    [[ "$cmd" =~ ${B}make[[:space:]]+clean ]] && deny "make clean (데이터 볼륨 삭제)"
    [[ "$cmd" =~ ${B}docker([[:space:]]+|-)compose[[:space:]]+down[[:space:]].*-v ]] && deny "docker compose down -v (데이터 볼륨 삭제)"
    [[ "$cmd" =~ ${B}alembic[[:space:]]+downgrade ]] && deny "alembic downgrade"
    # .env* 내용 덤프 금지 — 키 이름 확인(grep -c/-q '^KEY=', cut -d= -f1, sed -E 's/=.*//')만 허용
    if [[ "$cmd" =~ $ENV ]]; then
      [[ "$cmd" =~ ${B}(cat|less|more|head|tail|awk|bat|xxd|od|strings)([[:space:]]|$) ]] && deny ".env* 내용 출력 금지 — 키 이름만 확인하세요"
      [[ "$cmd" =~ ${B}sed[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*-n ]] && deny ".env* 내용 출력 금지 (sed -n)"
    fi
    [[ "$cmd" =~ ${B}git[[:space:]]+push ]] && ask "git push 는 사용자 확인이 필요합니다"
    [[ "$cmd" =~ ${B}launchctl[[:space:]]+kickstart ]] && ask "launchctl kickstart 는 사용자 확인이 필요합니다"
    ;;
esac
exit 0
