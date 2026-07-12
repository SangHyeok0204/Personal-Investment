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

import 후 워크플로를 열고 **Execute Workflow**를 누르면 테스트 작업이 생성된다.
worker가 작업을 처리하려면 먼저 `docker compose exec api alembic upgrade head`로 마이그레이션이 끝나 있어야 한다.
