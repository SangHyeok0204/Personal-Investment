---
name: page-health-sweep
description: 대시보드 전 페이지·API 건강 점검 — HTTP, 콘솔 오류, NaN/undefined 글자, 가로 넘침, 원천 상태, 화면 간 숫자 정합
---
# 페이지 건강 점검 (반복 작업 → skillify, 2026-10-04)

1. 서비스: `curl localhost:3000`, `curl localhost:8000/system/health` (API 루트 /health 는 404 가 정상).
2. 페이지 목록: `find apps/web/app -name page.tsx` → 경로.
3. 화면 스윕 — **두 회차에 한 번**(next dev 가 페이지를 열 때마다 컴파일해 메모리가 는다; 나머지 회차는 4·5·7번만)(설치된 크롬 headless — ms-playwright 번들 브라우저는 없다):
   `.venv/bin/python .omc/skills/page-health-sweep/sweep.py "/,/portfolio,..." > out.json`
   잡는 것: console error, HTTP ≥400, 본문의 NaN/undefined/Infinity/Invalid Date/null, 1280px 가로 넘침.
4. API: openapi.json 의 파라미터 없는 GET 전부 → 200·3초 이내. (422 = 필수 파라미터, 정상)
5. 원천: `/api/v1/jobs/sources`(state≠ok), `/api/v1/jobs?status=FAILED`, `/api/v1/brokerage/freshness`.
6. 정합(같은 숫자가 여러 화면에): summary.total_assets = Σholdings.market_value + cash,
   pnl-breakdown.total = realized + unrealized, account-return.pnl = total − unrealized_at_start.
7. 서버 자원: `ps -o rss,%cpu,etime -p $(lsof -ti tcp:3000|head -1)` — next dev RSS > 4GB 또는 홈 응답 > 3초면
   재시작 제안(사용자 승인 후 `cd apps/web && nohup npm run dev > /tmp/pi-web-dev.log 2>&1 &`). 2026-10-05 8일 가동 6.7GB·홈 10초 사례.
8. 결과는 `.omc/research/health-audit.md` 장부에 회차별로 남긴다. push 금지, exhibit.py 수정 금지.

- ★2026-10-09 입장 게이트: sweep.py 가 .env 비밀번호로 `/api/unlock` 을 불러 1시간 서명 토큰(`pi_session`)을 받는다(없으면 모든 화면이 / 로 307; 5회 틀리면 1분 잠금). `/performance`·`/news` 는 섹션 경로라 404 가 정상 — 하위 페이지(`/performance/returns` 등)를 넘긴다.
