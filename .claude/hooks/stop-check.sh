#!/usr/bin/env bash
# Stop 훅 — 변경 기반 센서. 깨끗한 트리면 즉시 통과(<0.2s).
#   .ts/.tsx 변경 → tsc,  .py 변경 → ruff(변경 파일) + 해당 앱 pytest,  둘 다 → 전부.
#   실패 → 출력 꼬리를 stderr 로, exit 2 (에이전트가 고친 뒤 턴을 끝낸다).
set -u
input=$(cat 2>/dev/null || true)
case "$input" in *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) exit 0 ;; esac

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0
untracked=$(git ls-files --others --exclude-standard -- '*.py' '*.ts' '*.tsx')
git diff --quiet && git diff --cached --quiet && [ -z "$untracked" ] && exit 0

# 새로 만든(추적 안 된) .py/.ts 도 본다 — git diff 에는 안 나온다.
changed=$( { git diff --name-only; git diff --cached --name-only; printf '%s\n' "$untracked"; } | sort -u)
ts=$(printf '%s\n' "$changed" | grep -E '\.tsx?$' || true)
py=$(printf '%s\n' "$changed" | grep -E '\.py$' | while read -r f; do [ -f "$f" ] && echo "$f"; done || true)
[ -z "$ts" ] && [ -z "$py" ] && exit 0

log=$(mktemp); trap 'rm -f "$log"' EXIT
fail() { echo "stop-check: $1 실패 — 고친 뒤 끝내라" >&2; tail -n 40 "$log" >&2; exit 2; }

if [ -n "$ts" ]; then
  (cd apps/web && node_modules/.bin/tsc --noEmit) >"$log" 2>&1 || fail "tsc"
fi
if [ -n "$py" ]; then
  # shellcheck disable=SC2086
  .venv/bin/ruff check --select E9,F63,F7,F82 $py >"$log" 2>&1 || fail "ruff"
  for app in api worker; do
    if printf '%s\n' "$py" | grep -q "^apps/$app/"; then
      (cd "apps/$app" && ../../.venv/bin/python -m pytest -q -x) >"$log" 2>&1 || fail "pytest ($app)"
    fi
  done
fi
exit 0
