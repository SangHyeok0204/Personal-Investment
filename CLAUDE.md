# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. 실행 명령 (호스트 기준)

Docker 가 아니라 **호스트**에서 돌린다(DB 는 로컬 Postgres :5432). 묻지 말고 아래 명령을 쓴다.

```text
BUILD : cd apps/web && npm run build:check
TYPE  : cd apps/web && npm run typecheck
TEST  : (cd apps/api && ../../.venv/bin/python -m pytest -q) && (cd apps/worker && ../../.venv/bin/python -m pytest -q)
        ↳ api → worker 를 따로, 차례로. 절대 병렬로 돌리지 않는다.
LINT  : .venv/bin/ruff check --select E9,F63,F7,F82 apps/api apps/worker
CHECK : make check
WORKERS: launchctl kickstart -k gui/$(id -u)/com.personal-investment.worker.{llm,sec_crawl}
        ↳ apps/worker 코드를 고치면 반드시 재시작한다(안 하면 옛 코드가 계속 돈다).
STOP  : touch storage/llm/STOP
```

**루프 규칙:** 변경할 때마다 테스트를 돌린다. 같은 오류로 3번 실패하면 멈추고 사용자에게 올린다.

**권한 가드:** `.claude/hooks/guard.sh` 가 `git reset --hard`·`make clean`·`docker compose down -v`·
`alembic downgrade`·`.env*` 내용 읽기를 막고, `git push`·`launchctl kickstart` 는 확인을 묻는다.
키 이름 확인(`grep -c '^KEY=' .env.local`, `cut -d= -f1`)은 허용된다.
push ask 의 bypass 모드 실측(`git push --dry-run`): **미확인(대기 중)** — 프롬프트가 안 뜨면 deny 로 바꾸고 여기에 기록한다.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 5. 키움 API 를 다룰 때 (이 저장소 전용)

**추측하지 말고 `api_guide.md` 를 먼저 본다.**

증권사 연동 코드를 쓰거나 고치기 전에:

- **`api_guide.md`** — 키움 REST API 공식 명세를 이 프로젝트 관점으로 정리한 문서.
  공통 규격(헤더·페이징·에러), 값 포맷 함정, 우리가 쓰는 TR 의 전체 필드표,
  로드맵별 TR 후보, 346개 TR 카탈로그가 들어 있다.
- **`docs/reference/kiwoom-rest-api-spec.json`** — 키움 공식 명세 원본(정본).
  필드 하나가 의심스러우면 요약본이 아니라 여기를 본다.
  ```bash
  python3 -c "import json;print(json.dumps(json.load(open('docs/reference/kiwoom-rest-api-spec.json'))['ust21070'],ensure_ascii=False,indent=1))"
  ```
- `docs/architecture/kiwoom-api-reference.md` 는 공식 문서 접근 전에 오픈소스 래퍼를
  역추적해 만든 문서다. **충돌하면 공식 명세가 이긴다.**

이 도메인에서 반복해 틀린 것들 — 전부 **예외가 안 나고 조용히 틀린다**:

- 금액·수량이 **0 패딩 문자열**("000000025789890")이고 환율에는 **콤마**가 섞인다.
- 수익률은 **퍼센트**다(5.16 = 5.16%). 시스템 안쪽은 비율(0.0516)로 통일한다 —
  변환은 증권사 경계에서 한 번만.
- KRW 환산은 **키움이 준 값**(`evlt_amt_krw`)을 쓴다. local × 환율로 만들지 않는다.
- `qty` 가 아니라 `poss_qty` 가 실제 보유수량이다.
- **HTTP 200 이어도 실패일 수 있다.** 본문 `return_code` 를 반드시 확인한다.
- 값이 없으면 **0 으로 채우지 않는다.** '모름'과 '0원'은 다르고, 0 으로 채우면
  화면이 없는 사실을 단언하게 된다.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
