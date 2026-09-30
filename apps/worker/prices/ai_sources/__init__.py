"""AI Key Data 원천 — 소스마다 한 파일, **순수 fetch/parse 만** (계획 S5, §11·§12-3).

원칙(드라이브 데몬 규칙 승계): **수집기는 판단하지 않는다.** 원값만 돌려준다.
평활·비중·델타·clip 은 API/화면 몫이다. 빈 응답은 실패로 본다(호출 쪽이 last-good 유지).

  npm · ramp · openrouter · tool_calling · epoch  — 과거를 매번 다시 받을 수 있다 → 라이브 + 메모리 캐시
  vscode · pypi                                    — 스냅샷만 된다 → `ai_metric_snapshot` 에 일 1회 적재

로스터·URL·UA 는 `config.py` 한 곳에 둔다.
"""
