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

> **내부 API 인증 헤더 (`X-Internal-API-Key`)**: HTTP Request 노드가 `X-Internal-API-Key` 헤더를 함께 보낸다. 값은 표현식 `={{ $env.INTERNAL_API_KEY }}`으로 n8n 컨테이너의 환경변수 `INTERNAL_API_KEY`를 읽는다. 이 변수는 `docker-compose.yml`의 n8n 서비스에 주입되며(값은 `.env`의 `INTERNAL_API_KEY`), 함께 설정한 `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` 덕분에 노드에서 `$env` 접근이 허용된다. API의 `/internal/*` 라우터는 이 헤더가 서버의 `INTERNAL_API_KEY`와 일치하지 않으면 **401 `UNAUTHORIZED`**를 반환한다. 즉 이 워크플로는 위 compose 환경설정이 반영된 상태에서만 동작한다.

## Import 방법

### 1) n8n UI에서
1. http://localhost:5678 접속
2. 우측 상단 메뉴 → **Import from File**
3. `workflows/n8n/create-test-job.json` 선택

### 2) 명령줄에서
`./workflows/n8n`은 n8n 컨테이너의 `/workflows`(읽기 전용)로 마운트되어 있다.

```bash
docker compose exec n8n n8n import:workflow --input=/workflows/create-test-job.json
```

import 후 워크플로를 열고 **Execute Workflow**를 누르면 작업이 생성된다. worker가 작업을 처리하려면 먼저 `docker compose exec api alembic upgrade head`로 마이그레이션이 끝나 있어야 하고, `.env`에 `INTERNAL_API_KEY`가 있어야 한다(compose가 n8n·api에 주입).
