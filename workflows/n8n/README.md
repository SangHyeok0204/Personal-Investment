# n8n 워크플로

## Create Test Job (`create-test-job.json`)

n8n에서 FastAPI 내부 작업 생성 API를 호출할 수 있는지 검증하는 최소 워크플로다.

- **목적 (Purpose)**: `n8n → FastAPI POST /internal/jobs` 연동이 동작하는지 확인한다.
- **트리거 (Trigger)**: Manual Trigger (수동 실행).
- **입력 (Input)**: 없음. HTTP Request 노드에 요청 본문이 고정되어 있다.
- **호출 API**: `POST http://api:8000/internal/jobs`
  - body: `{ "job_type": "TEST_JOB", "payload": { "source": "n8n" } }`
- **출력 (Output)**: FastAPI가 반환하는 Job JSON (`id`, `status: PENDING`, ...). 이후 worker가 이 작업을 집어 SUCCESS로 바꾼다.
- **실패 처리 (Failure handling)**: API가 4xx/5xx를 반환하면 HTTP Request 노드가 실패하고 실행이 중단된다. n8n의 **Executions** 화면에서 응답 상태 코드와 본문을 확인한다. `http://api:8000`은 Docker 내부 DNS이므로 n8n 컨테이너 안에서만 접근된다 (브라우저에서 직접 열리지 않는다).

> **내부 API 인증 헤더 (`X-Internal-API-Key`)**: 아래 두 워크플로의 HTTP Request 노드는 모두 `X-Internal-API-Key` 헤더를 함께 보낸다. 값은 표현식 `={{ $env.INTERNAL_API_KEY }}`으로 n8n 컨테이너의 환경변수 `INTERNAL_API_KEY`를 읽는다. 이 변수는 `docker-compose.yml`의 n8n 서비스에 주입되며(값은 `.env`의 `INTERNAL_API_KEY`), 함께 설정한 `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` 덕분에 노드에서 `$env` 접근이 허용된다. API의 `/internal/*` 라우터는 이 헤더가 서버의 `INTERNAL_API_KEY`와 일치하지 않으면 **401 `UNAUTHORIZED`**를 반환한다. 즉 이 워크플로들은 위 compose 환경설정이 반영된 상태에서만 동작한다.

## Sync Kiwoom Portfolio (`portfolio/sync-kiwoom-portfolio.json`)

키움증권 REST API로 계좌·잔고·보유종목을 동기화하는 작업(`SYNC_KIWOOM_PORTFOLIO`)을 내부 작업 API로 생성하는 워크플로다.

- **목적 (Purpose)**: `n8n → FastAPI POST /internal/jobs`로 키움 포트폴리오 동기화 작업을 큐에 넣는다. 실제 키움 API 호출과 DB 반영은 worker가 담당한다.
- **트리거 (Trigger)**: Manual Trigger (수동 실행). 스케줄 자동화는 아래 가이드 참고.
- **호출 API**: `POST http://api:8000/internal/jobs`
  - header: `X-Internal-API-Key: ={{ $env.INTERNAL_API_KEY }}`
  - body: `{ "job_type": "SYNC_KIWOOM_PORTFOLIO", "payload": {} }`
- **출력 (Output)**: 생성된 Job JSON (`id`, `status: PENDING`, ...). worker가 집어 처리하며, 진행·결과는 대시보드 `/` 또는 `GET /api/v1/jobs/{id}`로 확인한다.
- **실패 처리 (Failure handling)**:
  - 인증 실패(헤더 누락/불일치) → API가 **401 `UNAUTHORIZED`** → HTTP Request 노드 실패. `.env`와 compose의 `INTERNAL_API_KEY`가 일치하는지 확인한다.
  - 키움 키(`KIWOOM_APP_KEY`/`KIWOOM_SECRET_KEY`) 미설정 → 작업 **생성은 성공**하지만 worker가 `validate_configuration` 단계에서 깨끗하게 FAILED 처리한다(오류 메시지에 "not configured" 포함). 미설정 상태의 정상 동작이며, 대시보드 Data Operations 작업 로그에서 확인한다.
  - 그 외 4xx/5xx → **Executions** 화면에서 상태 코드·본문을 확인한다.

### 스케줄 추가 (안정화 후)

수동 실행으로 키움 키가 정상 동작하는 것을 확인한 뒤, Manual Trigger를 **Schedule Trigger**로 바꾸거나 병행해 자동화할 수 있다. 한국 시장 기준 예시(모두 KST):

- **장전 08:30** — 장 시작 전 스냅샷
- **장후 16:00** — 국내장 마감 반영
- **미국장 마감 후 06:30** — 미국주식 평가금액 반영 (서머타임에 따라 06:00~07:00 사이로 조정)

Schedule Trigger 노드를 추가하고 Cron 식(예: 평일 08:30은 `30 8 * * 1-5`)으로 거래일에만 돌리는 것을 권장한다. 동기화 작업은 멱등(idempotent)이라 — 같은 연결에 PENDING/RUNNING 작업이 있으면 새로 만들지 않고 재사용한다 — 중복 트리거가 있어도 안전하다.

## Import 방법

### 1) n8n UI에서
1. http://localhost:5678 접속
2. 우측 상단 메뉴 → **Import from File**
3. 등록할 파일 선택:
   - `workflows/n8n/create-test-job.json`
   - `workflows/n8n/portfolio/sync-kiwoom-portfolio.json`

### 2) 명령줄에서
`./workflows/n8n`은 n8n 컨테이너의 `/workflows`(읽기 전용)로 마운트되어 있다. 서브폴더 경로도 그대로 유지된다.

```bash
docker compose exec n8n n8n import:workflow --input=/workflows/create-test-job.json
docker compose exec n8n n8n import:workflow --input=/workflows/portfolio/sync-kiwoom-portfolio.json
```

import 후 워크플로를 열고 **Execute Workflow**를 누르면 해당 작업이 생성된다.
worker가 작업을 처리하려면 먼저 `docker compose exec api alembic upgrade head`로 마이그레이션이 끝나 있어야 한다. `Sync Kiwoom Portfolio`는 추가로 `.env`에 `INTERNAL_API_KEY`가 있어야 하며(compose가 n8n·api에 주입), 실제 성공하려면 `KIWOOM_APP_KEY`/`KIWOOM_SECRET_KEY`도 필요하다.
