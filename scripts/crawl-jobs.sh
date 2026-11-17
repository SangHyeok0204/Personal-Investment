#!/bin/bash
# 채용 공고 다시 수집 — finance-jobs 스킬 크롤러를 돌려 화면 [채용 공고](/careers)의 원천을 바꾼다.
#
# ★2026-11-02 사용자 요청. 원천은 storage/jobs/postings.json(API GET /api/v1/careers/postings).
# ⚠️이 스크립트는 크롤러 원본 그대로 쓴다 — 빈 칸(직무·근무시기) 보완·중복 합치기는 스킬 2단계라
#   Claude 에게 "채용 공고 갱신해줘" 로 맡기면 채워진다. 빈 칸은 화면에서 '공고 확인' 으로 보인다.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/storage/jobs/postings.json"
mkdir -p "$(dirname "$OUT")"
# ★2026-11-06 매 정시 LaunchAgent(com.personal-investment.jobs-crawl)가 부른다 — 외부 크롤은 프로세스 단위
#   시간 제한(CLAUDE.md L4). macOS 엔 timeout 이 없어 perl alarm 으로 15분 뒤 강제 종료한다.
#   실패하면 tmp 만 남고 기존 postings.json 은 그대로다.
perl -e 'alarm shift; exec @ARGV' 900 \
  python3 "$HOME/.claude/skills/finance-jobs/scripts/crawl_jobs.py" --days "${1:-14}" -o "$OUT.tmp"
# ★2026-11-06 잠자기·DNS 끊김 중의 회차가 출처 대부분을 못 받은 채 좋은 파일을 덮어쓰지 않게 —
#   공고 0건이거나 출처 절반 이상이 실패하면 새 결과를 버리고 기존 파일을 둔다.
# ★2026-11-16 출처 하나만 실패해도 그 출처 공고가 화면에서 통째로 사라졌다(univ 연결 끊김 → 70→61건).
#   받아들이는 회차에서도 실패한 출처는 직전 파일의 공고를 이어 쓴다(같은 url 은 한 번만).
if [ -f "$OUT" ] && ! python3 - "$OUT.tmp" "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
src = d.get("sources", [])
failed = [s["key"] for s in src if s.get("error") or not s.get("crawled")]
if not d.get("jobs") or len(failed) * 2 >= max(len(src), 1):
    print(f"건너뜀: 공고 {len(d.get('jobs', []))}건, 실패 출처 {failed} — 기존 postings.json 유지")
    sys.exit(1)
if failed:
    old = json.load(open(sys.argv[2])).get("jobs", [])
    seen = {j.get("url") for j in d["jobs"]}
    kept = [j for j in old if j.get("source") in failed and j.get("url") not in seen]
    d["jobs"].extend(kept)
    json.dump(d, open(sys.argv[1], "w"), ensure_ascii=False, indent=2)
    print(f"실패 출처 {failed} — 직전 공고 {len(kept)}건 이어 씀")
PY
then
  rm -f "$OUT.tmp"
  exit 0
fi
mv "$OUT.tmp" "$OUT"
echo "$(date '+%F %T') → $OUT"
