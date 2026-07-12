# 인수인계 문서 — 개인 투자 플랫폼 초기 골격

> 2026-07-12 초기 구현 완료 시점 기준. 이 문서 하나로 "시스템이 어떻게 돌고, 다음 기능을 어디에 어떻게 붙이는지"를 파악할 수 있게 쓴다.
> 상세 스펙은 `init.md`, 전체 설계는 `personal_investment_dashboard_architecture.md`, 서비스 간 인터페이스 계약은 `docs/architecture/contract.md`, 실행 방법은 `README.md`.

---

## 1. 한 장 요약 — 이 시스템이 도는 방식

```
[브라우저]
  localhost:3000  대시보드 (Next.js)      ← 보는 곳
  localhost:5678  n8n                     ← 자동화 지휘소
  localhost:8000/docs  API 문서(Swagger)  ← 개발 확인용

[Docker 내부]
  web ──REST──▶ api ──SQL──▶ postgres ◀──polling── worker
                 ▲                                    │
  n8n ──POST /internal/jobs──┘        storage/ ◀──파일 읽고 쓰기──┘
```

핵심 개념은 **작업(job)** 하나다. 모든 백그라운드 일은 다음 한 가지 흐름으로 통일된다:

```
누군가(화면 버튼 or n8n)가 API에 "작업 만들어줘" 요청
→ jobs 테이블에 PENDING 행 생성
→ worker가 2초마다 PENDING을 집어감 (중복 방지: FOR UPDATE SKIP LOCKED)
→ RUNNING으로 바꾸고 처리
→ SUCCESS 또는 FAILED + 결과/에러 기록, job_logs에 단계 로그
→ 대시보드가 폴링으로 상태·로그 표시
```

앞으로 어떤 기능(시세 수집, 뉴스 크롤링, 백테스트...)을 추가하든 **"새 job_type 하나 추가"** 로 수렴한다. 이 레시피가 §4에 있다.

---

## 2. 영역별 설명

### 2.1 `apps/web` — 대시보드 (계기판)

- **역할**: 보여주기만 한다. DB에 직접 접근하지 않고 오직 API만 호출한다.
- **기술**: Next.js 15(App Router) + TypeScript + Tailwind + TanStack Query. 페이지는 전부 클라이언트 컴포넌트이고 3~5초 간격 폴링으로 갱신된다.
- **화면 3개**: Overview(연결 상태 + 작업 통계), Data Operations(테스트 작업 실행 / CSV 업로드 / 작업 테이블 + 상세 패널), Settings(읽기 전용).
- **디자인**: `DESIGN.md`의 노션 스타일 — 웜 캔버스, 흰 카드 + 헤어라인, 파란색(#0075de) 하나만 액센트, 상태는 작은 도트(성공 초록/실행 하늘/실패 빨강).
- **수정 지도**:
  - 새 화면 → `app/<경로>/page.tsx` + `components/layout/sidebar.tsx`에 메뉴 추가
  - 새 API 호출 → `lib/api.ts`에 타입과 함수 추가(모든 호출이 여기로 모임)
  - UI 부품 → `components/ui/`(버튼·카드·테이블 등 공용), `components/`(도메인 부품)
- **주의**: `NEXT_PUBLIC_API_BASE_URL`은 **빌드 시점에 박제**된다. API 주소를 바꾸면 web 재빌드 필요.

### 2.2 `apps/api` — FastAPI (접수창구 + 사무소)

- **역할**: 요청 검증 → 업무 규칙 → DB 읽기/쓰기 → 작업 생성. 유일하게 DB에 "쓰는 관문"이다(worker 제외).
- **라우터 구분** (주소만 봐도 용도를 알 수 있게):
  - `/api/v1/*` — 대시보드가 쓰는 일반 API (jobs 목록/상세/통계, CSV 업로드)
  - `/internal/*` — n8n·자동화가 쓰는 내부 API (현재 인증 없음, 다음 단계에 추가 예정)
  - `/system/*` — 헬스체크
- **에러 포맷 통일**: 실패 응답은 항상 `{"error": {"code", "message", "details"}}`. 화면과 n8n이 이 형식만 처리하면 된다.
- **수정 지도**: 엔드포인트 추가 = `app/api/<도메인>.py`에 라우터 → `app/schemas.py`에 요청/응답 모델 → 필요하면 `app/models.py` + 마이그레이션(§2.4). `main.py`에 라우터 등록.

### 2.3 `apps/worker` — 일꾼 (실제 노동)

- **역할**: 오래 걸리는 일 전부. 지금은 TEST_JOB(데모)과 CSV_IMPORT(검증→정규화→저장) 두 가지.
- **동작**: Redis/Celery 없이 PostgreSQL 폴링. `FOR UPDATE SKIP LOCKED`라서 워커를 여러 개 띄워도 같은 작업을 두 번 처리하지 않는다.
- **구조**: `main.py`(루프) / `handlers/`(작업 유형별 처리 함수 + 레지스트리) / `joblog.py`(단계 로그).
- **새 작업 유형 추가 = 파일 하나 + 등록 한 줄** (§4.1 레시피 참고). 모르는 job_type이 오면 FAILED("Unknown job type")로 안전하게 끝난다.

### 2.4 `database/` + PostgreSQL — 장부

- **테이블 3개**: `jobs`(작업 현황판), `job_logs`(작업별 단계 로그), `imports`(파일 업로드 기록).
- **스키마 변경 규칙**: 앱이 테이블을 자동 생성하지 않는다. 반드시 Alembic으로:
  ```bash
  docker compose exec api alembic revision -m "add xxx table"   # database/migrations/versions/에 파일 생성
  # 생성된 파일에 upgrade/downgrade 직접 작성 (0001_initial.py 참고)
  docker compose exec api alembic upgrade head
  ```
- **데이터 보존**: postgres는 named volume(`postgres_data`). `docker compose down`은 안전, **`down -v`는 전부 삭제**.

### 2.5 `workflows/n8n` + n8n — 자동화 지휘소

- **역할 분담 원칙** (아키텍처 문서의 핵심 규칙):
  ```
  n8n    = 언제, 어떤 순서로 실행할지 (트리거·분기·재시도·이력)
  Python = 실제로 무엇을 계산하고 처리할지 (worker handler)
  ```
  n8n 안에 pandas나 금융 계산을 넣지 않는다. n8n은 API를 부르는 것까지만.
- 자세한 작업 방법은 §3.

### 2.6 `storage/` — 서류함

- `raw/` 원본 그대로(수정 금지), `processed/` 가공 결과. api·worker 컨테이너에 `/app/storage`로 마운트, n8n에는 `/files`로 마운트.
- 새 파일 종류가 생기면 하위 폴더를 늘린다(추후 설계 문서의 staging/curated/analytics 단계 참고).

### 2.7 인프라 — `docker-compose.yml`, `.env`, `Makefile`

- 자주 쓰는 명령: `make up` `make down` `make logs` `make migrate` `make test` `make integration` `make ps`
- 환경변수는 전부 `.env`(git 제외). 새 변수 추가 시 `.env.example`에도 반드시 추가.
- 컨테이너끼리는 서비스 이름으로 통신: `http://api:8000`, `postgres:5432`. **컨테이너 안에서 localhost 금지.**

---

## 3. n8n 작업 가이드 (인수인계 핵심)

### 3.1 처음 한 번

1. 스택 기동 후 http://localhost:5678 접속 → 최초 1회 오너 계정 생성(로컬 전용 계정).
2. 기존 워크플로 가져오기:
   - UI: 좌측 메뉴 → Workflows → Import from File → `workflows/n8n/create-test-job.json`
   - CLI: `docker compose exec n8n n8n import:workflow --input=/workflows/create-test-job.json`
3. "Create Test Job" 워크플로를 열고 Execute Workflow 클릭 → 대시보드 Data Operations에 TEST_JOB이 나타나면 연동 정상.

### 3.2 외우면 되는 기본 패턴 하나

모든 자동화는 이 모양이다:

```
[Trigger 노드]  Schedule(크론) 또는 Manual 또는 Webhook
      ↓
[HTTP Request 노드]  POST http://api:8000/internal/jobs
      Body(JSON): {"job_type": "작업이름", "payload": {...파라미터...}}
      ↓ 응답으로 작업 id가 돌아옴
[선택: 상태 확인]  GET http://api:8000/api/v1/jobs/{{ $json.id }}
[선택: 분기]      IF 노드로 status가 SUCCESS/FAILED인지에 따라 후속 처리
```

**가장 흔한 실수**: URL에 `http://localhost:8000`을 쓰는 것. n8n은 컨테이너 안에 있으므로 반드시 `http://api:8000`.

### 3.3 새 자동화 추가 전체 레시피 (예: 평일 아침 시세 수집)

**1단계 — worker에 handler 추가** (`apps/worker/handlers/collect_market_data.py`, 실제 시그니처 그대로):
```python
def run(engine, job_id, payload, storage_dir, log_job):
    payload = payload or {}
    log_job(engine, job_id, "INFO", "start", f"collecting for {payload.get('tickers')}")
    # ... 실제 수집/저장 로직 ...
    log_job(engine, job_id, "INFO", "done", "collected 123 rows")
    return {"collected": 123}          # 이 dict가 jobs.result(JSONB)에 저장됨
```
`handlers/__init__.py` 레지스트리에 등록:
```python
from . import collect_market_data, csv_import, test_job

HANDLERS = {
    "TEST_JOB": test_job.run,
    "CSV_IMPORT": csv_import.run,
    "COLLECT_MARKET_DATA": collect_market_data.run,   # ← 추가
}
```
(기존 `test_job.py`가 최소 예제, `csv_import.py`가 파일·DB를 다루는 예제다. `log_job`으로 남긴 단계 로그는 대시보드 상세 패널에 타임라인으로 보인다. 예외를 던지면 자동으로 FAILED + error_message가 된다.)

**2단계 — worker 반영**:
```bash
docker compose build worker && docker compose up -d worker
```

**3단계 — n8n 워크플로 작성**:
- Schedule Trigger: Cron `0 8 * * 1-5` (평일 08:00, 타임존은 GENERIC_TIMEZONE=Asia/Seoul 적용)
- HTTP Request: POST `http://api:8000/internal/jobs`, Body `{"job_type":"COLLECT_MARKET_DATA","payload":{"tickers":["005930","000660"]}}`

**4단계 — 확인**: 대시보드 Data Operations에서 작업이 SUCCESS로 끝나는지, 로그 타임라인이 남는지 확인.

**5단계 — 커밋(중요)**: n8n UI에서 워크플로 Export(JSON) → `workflows/n8n/market/daily-market-update.json`처럼 영역별 폴더에 저장 → `workflows/n8n/README.md`에 목적/트리거/호출 API 한 줄 기록 → git 커밋. n8n 내부 저장(volume)만 믿지 말 것 — JSON이 git에 있어야 재현 가능하다.

### 3.4 실패 처리와 재시도

- **n8n 수준**: HTTP Request 노드 Settings → Retry On Fail(횟수·간격). 워크플로 실행 이력은 n8n Executions 탭에서 확인.
- **작업 수준**: 처리 실패는 jobs.error_message + job_logs(ERROR)로 남고 대시보드에서 보인다. 같은 작업을 다시 돌리려면 새 작업을 만들면 된다(작업은 불변 기록).
- **원칙**: "재시도해도 안전한가?"는 handler가 책임진다(멱등하게 작성 — 예: 같은 날짜 데이터는 upsert).

### 3.5 n8n에서 하지 말 것

- Code 노드에 계산 로직 쌓기 (→ worker handler로)
- `/api/v1/*`를 자동화에서 호출 (→ 자동화는 `/internal/*`만; 나중에 인증을 /internal에만 붙일 계획이라 경계를 지켜야 함)
- N8N_ENCRYPTION_KEY 변경 (저장된 크리덴셜이 전부 깨짐)

---

## 4. 개발 루틴 요약

| 무엇을 바꿨나 | 반영 방법 |
|---|---|
| web 코드 | `docker compose build web && docker compose up -d web` (빠른 개발: `cd apps/web && npm run dev` — WSL에서 직접, API는 localhost:8000 그대로 씀) |
| api 코드 | `docker compose build api && docker compose up -d api` |
| worker 코드 | `docker compose build worker && docker compose up -d worker` |
| DB 스키마 | alembic revision 작성 → `make migrate` |
| n8n 워크플로 | UI에서 작업 → Export JSON → workflows/n8n/에 커밋 |

검증 습관: `make test`(api 21 + worker 3), `make integration`(E2E), `docker compose ps`(healthy 확인), `make logs`.

---

## 5. 다음 개발 로드맵 (설계 문서와의 연결)

1. **Phase 4 — 첫 실제 도메인** (아키텍처 §21): 계좌·거래·보유자산 테이블(portfolio 스키마) + CSV를 실제 포트폴리오에 적재하는 handler + Portfolio 화면.
2. **키움증권 연동** — ✅ 2라운드에서 구현 완료 (2026-07-12). REST API 기반 `SYNC_KIWOOM_PORTFOLIO` 작업 + 포트폴리오 화면 + `/internal` 키 인증까지 반영. 인터페이스 계약은 `docs/architecture/contract-kiwoom.md`, 키움 API 필드 근거는 `docs/architecture/kiwoom-api-reference.md`, 키 설정 방법은 README §15. 남은 것: 실키 입력 후 TO-VERIFY 상수(enum 값·숫자 스케일) 모의투자 확정, 미국주식은 공식 문서 확인 후 활성화(`us_supported=false` 게이트).
3. **시장 데이터 수집**: §3.3 레시피 그대로. 데이터가 커지면 그때 Parquet + DuckDB 도입(아키텍처 §4.5).
4. **뉴스·공시 수집** → research 스키마.
5. 지금 넣지 않기로 한 것(init.md §18: Redis, Celery, AI, 백테스트, 자동매매 등)은 필요성이 명확해질 때까지 추가하지 않는다.

---

## 6. 트러블슈팅 FAQ

| 증상 | 원인/해결 |
|---|---|
| 대시보드에 "API unreachable" 배너 | api 컨테이너 확인: `docker compose ps`, `docker compose logs api`. Docker Desktop이 꺼져 있으면 전부 안 뜸 |
| n8n HTTP Request가 connection refused | URL이 `localhost:8000`으로 되어 있음 → `http://api:8000`으로 |
| 작업이 PENDING에서 안 움직임 | worker가 죽어 있음: `docker compose logs worker` |
| `docker compose up` 환경변수 경고 | `.env` 없음 → `cp .env.example .env` |
| 5432/3000/8000/5678 포트 충돌 | 해당 포트를 쓰는 다른 프로그램 종료 후 재시도 |
| 데이터가 몽땅 사라짐 | `down -v`를 썼을 가능성. 평소엔 `make down`만 |
| CSV 업로드가 FAILED | 작업 상세 패널의 error_message 확인 (필수 컬럼: account_name, ticker, asset_name, quantity) |
| 스키마 바꿨는데 api가 에러 | 마이그레이션 미적용 → `make migrate` |

---

## 7. 문서 지도

| 문서 | 용도 |
|---|---|
| `README.md` | 처음 실행하는 법 (설치→기동→확인) |
| `init.md` | 이번 단계의 요구사항 스펙 (무엇을/무엇은 안) |
| `personal_investment_dashboard_architecture.md` | 전체 그림과 장기 로드맵 |
| `DESIGN.md` | UI 디자인 시스템 (색·타이포·컴포넌트 규칙) |
| `docs/architecture/contract.md` | 서비스 간 인터페이스 계약 (API 형태·DB DDL·작업 유형) — **기능 추가 시 여기부터 갱신** |
| `docs/screenshots/` | 초기 완성 시점의 화면 |
| 이 문서 | 개발을 이어가는 법 |
