#!/bin/bash
# 회차 점검 한 번에 — 가벼운 점검(원천·IP·메모리·게이트), FULL=1 이면 전 화면 스윕까지.
# 사용: bash .omc/skills/page-health-sweep/tick.sh   |   FULL=1 bash .omc/skills/page-health-sweep/tick.sh
cd "$(dirname "$0")/../../.." || exit 1
date
curl -s -m 10 localhost:8000/api/v1/jobs/sources | python3 -c "
import json,sys;d=json.load(sys.stdin);d=d.get('items',d) if isinstance(d,dict) else d
print('sources not ok:',[(s['source'],s['state']) for s in d if s['state'] not in ('ok','alive')])" || echo "api: down"
echo "public ip: $(curl -s -m 5 https://api.ipify.org)"
PID=$(lsof -ti tcp:3000 -sTCP:LISTEN | head -1)
[ -n "$PID" ] && ps -o rss= -p "$PID" | awk '{printf "web RSS %.1fGB (4GB 넘으면 재시작 제안)\n",$1/1048576}' || echo "web: down"
echo "gate(no token) $(curl -s -o /dev/null -w '%{http_code}' localhost:3000/portfolio) | landing $(curl -s -o /dev/null -w '%{http_code} %{time_total}s' localhost:3000/)"
if [ "$FULL" = 1 ]; then
  PAGES=$(cd apps/web && find app -name page.tsx | grep -v '\[' | sed 's#^app##; s#/page.tsx$##' | grep -v '^$' | sort | paste -sd, -)
  .venv/bin/python .omc/skills/page-health-sweep/sweep.py "$PAGES" | python3 -c "
import json,sys;d=json.load(sys.stdin);bad={k:v for k,v in d.items() if any(v[x] for x in ('console','http','bad_text','overflow','loading'))}
print(f'sweep: {len(d)} pages, {len(bad)} with issues');[print(' ',k,v) for k,v in bad.items()]"
fi
