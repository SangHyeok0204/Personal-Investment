# 개인 투자 플랫폼 초기 구현 요청서

> **이 문서는 2026-07 초기 요청서다 — 현행 사양이 아니다.** 당시 무엇을 시켰는지 남기는 기록물이라
> 일부러 갱신하지 않는다. 지금 시스템이 어떻게 도는지는 `README.md`, 이어서 개발하는 법은
> `docs/HANDOVER.md` 를 본다. (§2-11 키움 항목은 구현했다가 커밋 80fad01 에서 전면 제거됐다.)

## 1. 프로젝트 목표

Windows + WSL2 + Docker Desktop 환경에서 실행되는 로컬 개인 투자 플랫폼의 초기 골격을 구현한다.

이번 단계의 목적은 실제 투자 분석 기능을 만드는 것이 아니다.

다음 수직 흐름이 처음부터 끝까지 정상 작동하도록 만드는 것이 목표다.

```text
Next.js 화면에서 작업 실행
→ FastAPI가 작업 생성
→ PostgreSQL에 작업 상태 저장
→ Python Worker가 작업 처리
→ PostgreSQL 작업 상태 갱신
→ Next.js에서 진행 결과 확인
```

n8n에서도 같은 FastAPI 작업 생성 API를 호출할 수 있어야 한다.

---

# 2. 이번 단계의 구현 범위

이번 단계에서는 다음 기능만 구현한다.

1. Docker Compose 기반 로컬 실행환경
2. Next.js 기본 대시보드
3. FastAPI 기본 API 서버.
4. 로컬 PostgreSQL
5. Python Worker
6. 작업 상태 관리
7. n8n 연동
8. 테스트용 CSV 파일 업로드 및 처리
9. 기본 로그와 오류 처리
10. README 실행 가이드
11. 키움증권 계좌 할용예정 --> 키움 API 통한 계좌 자산 현황 불러오기 구현

구체적인 투자 지표, 뉴스 크롤링, 퀀트 분석, 백테스트, AI 기능은 구현하지 않는다.

---

# 3. 기술 스택

```text
Frontend
- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query

Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic

Worker
- Python 별도 프로세스
- PostgreSQL polling 방식

Database
- PostgreSQL

Workflow
- n8n

Infrastructure
- Docker Compose

Development Environment
- Windows
- WSL2 Ubuntu
- Docker Desktop
```

이번 단계에서는 Redis, Celery, Kafka, DuckDB, Parquet, Elasticsearch, MinIO를 사용하지 않는다.

---

# 4. 핵심 아키텍처

```text
Browser
├── localhost:3000 → Next.js
└── localhost:5678 → n8n

Docker Network
├── web
├── api
├── worker
├── postgres
└── n8n
```

서비스 간 통신 주소:

```text
Next.js server → http://api:8000
n8n            → http://api:8000
FastAPI        → postgres:5432
Worker         → postgres:5432
```

컨테이너 내부 통신에 `localhost`를 사용하지 않는다.

---

# 5. 초기 폴더 구조

```text
personal-investment-platform/
│
├── apps/
│   ├── web/
│   ├── api/
│   └── worker/
│
├── database/
│   ├── migrations/
│   └── seeds/
│
├── workflows/
│   └── n8n/
│
├── storage/
│   ├── raw/
│   └── processed/
│
├── docs/
│   └── architecture/
│
├── scripts/
│
├── docker-compose.yml
├── .env.example
├── Makefile
└── README.md
```

이번 단계에서는 복잡한 `packages`, `services`, 마이크로서비스 구조를 추가하지 않는다.

각 애플리케이션 내부에서 기능별 모듈화를 적용하되, 지나친 추상화는 피한다.

---

# 6. 구현할 데이터 모델

## 6.1 jobs

백그라운드 작업의 현재 상태를 저장한다.

```text
id UUID PRIMARY KEY
job_type VARCHAR
status VARCHAR
payload JSONB
result JSONB
error_message TEXT
created_at TIMESTAMPTZ
started_at TIMESTAMPTZ
finished_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

허용 상태:

```text
PENDING
RUNNING
SUCCESS
FAILED
```

## 6.2 job_logs

작업 단계별 로그를 저장한다.

```text
id UUID PRIMARY KEY
job_id UUID FOREIGN KEY
level VARCHAR
step VARCHAR
message TEXT
metadata JSONB
created_at TIMESTAMPTZ
```

로그 수준:

```text
INFO
WARNING
ERROR
```

## 6.3 imports

파일 업로드 기록을 저장한다.

```text
id UUID PRIMARY KEY
job_id UUID FOREIGN KEY
original_filename VARCHAR
stored_filename VARCHAR
file_path VARCHAR
file_size BIGINT
status VARCHAR
row_count INTEGER
created_at TIMESTAMPTZ
```

---

# 7. 첫 번째 실제 작업

테스트 작업으로 CSV 파일 업로드 및 처리를 구현한다.

## 입력 CSV 예시

```csv
account_name,ticker,asset_name,quantity
Main Account,000660,SK Hynix,10
Main Account,005930,Samsung Electronics,20
```

## 처리 흐름

```text
1. 사용자가 Next.js에서 CSV 파일 선택
2. Next.js가 FastAPI에 multipart/form-data로 업로드
3. FastAPI가 파일을 storage/raw에 저장
4. FastAPI가 jobs 테이블에 PENDING 작업 생성
5. FastAPI가 job_id 반환
6. Worker가 PENDING 작업 조회
7. Worker가 상태를 RUNNING으로 변경
8. CSV 헤더와 행을 검증
9. 처리된 결과를 storage/processed에 저장
10. imports 테이블에 처리 결과 저장
11. 작업 상태를 SUCCESS로 변경
12. 실패 시 FAILED와 error_message 저장
13. Next.js가 작업 상태를 주기적으로 조회
14. 완료 결과를 화면에 표시
```

이번 단계에서는 CSV 내용을 실제 포트폴리오 테이블에 적재하지 않는다.

CSV 파일 처리와 작업 상태 추적까지만 구현한다.

---

# 8. FastAPI 엔드포인트

## 시스템 상태

```text
GET /system/health
```

응답 예시:

```json
{
  "status": "ok",
  "database": "connected"
}
```

## 작업 생성

```text
POST /api/v1/jobs/test
```

테스트용 백그라운드 작업을 생성한다.

## 작업 목록

```text
GET /api/v1/jobs
```

## 작업 상세

```text
GET /api/v1/jobs/{job_id}
```

작업 상태와 로그를 함께 반환한다.

## CSV 업로드

```text
POST /api/v1/imports/csv
```

파일을 저장하고 CSV 처리 작업을 생성한다.

## 내부 작업 생성

```text
POST /internal/jobs
```

n8n에서 호출할 수 있는 내부 API다.

요청 예시:

```json
{
  "job_type": "TEST_JOB",
  "payload": {
    "source": "n8n"
  }
}
```

이번 단계에서는 인증을 구현하지 않지만, `/internal` API는 향후 인증을 추가할 수 있도록 별도 라우터로 분리한다.

---

# 9. Worker 구현 방식

초기에는 Redis나 Celery를 사용하지 않는다.

Worker는 PostgreSQL의 `jobs` 테이블을 주기적으로 조회한다.

```text
1. PENDING 작업 1건 조회
2. 해당 작업을 RUNNING으로 원자적 변경
3. 작업 유형에 따라 handler 실행
4. 성공 시 SUCCESS
5. 실패 시 FAILED
6. 실행 로그 저장
7. 다음 작업 조회
```

동일 작업이 중복 처리되지 않도록 PostgreSQL row locking을 사용한다.

예:

```sql
SELECT *
FROM jobs
WHERE status = 'PENDING'
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Worker polling 간격은 환경변수로 설정한다.

```text
WORKER_POLL_INTERVAL_SECONDS=2
```

---

# 10. Next.js 초기 화면

## 공통 레이아웃

```text
Sidebar
├── Overview
├── Data Operations
└── Settings
```

이번 단계에서는 위 세 메뉴만 만든다.

## Overview

표시 내용:

* API 연결 상태
* DB 연결 상태
* 최근 작업 상태
* 전체 작업 수
* 성공·실패 작업 수

## Data Operations

표시 내용:

* CSV 업로드 영역
* 테스트 작업 실행 버튼
* 작업 목록 테이블
* 작업 상태
* 작업 생성 시간
* 작업 완료 시간
* 작업 상세 보기
* 작업 로그

## Settings

표시 내용:

* 현재 API 주소
* 실행환경 정보
* 읽기 전용 시스템 정보

실제 설정 수정 기능은 구현하지 않는다.

---

# 11. n8n 초기 워크플로

n8n에서 다음 워크플로 하나를 구현한다.

```text
Manual Trigger
→ HTTP Request
→ FastAPI POST /internal/jobs
→ 응답 확인
```

워크플로 이름:

```text
Create Test Job
```

워크플로는 JSON으로 export하여 다음 경로에 저장한다.

```text
workflows/n8n/create-test-job.json
```

README에 n8n에서 워크플로를 import하는 방법을 작성한다.

---

# 12. Docker Compose 서비스

```text
web
api
worker
postgres
n8n
```

필수 요구사항:

* 서비스 이름으로 내부 통신
* PostgreSQL named volume 사용
* n8n named volume 사용
* `storage` 폴더는 api와 worker가 공유
* healthcheck 추가
* 서비스 시작 순서에 health condition 적용
* 모든 환경변수는 `.env`에서 주입
* 비밀번호를 코드에 하드코딩하지 않음

외부 포트:

```text
3000 → Next.js
5678 → n8n
8000 → FastAPI 개발 확인용
5432 → PostgreSQL 개발 확인용
```

PostgreSQL 외부 포트는 개발 편의를 위해 열되, README에 운영 시 제거할 수 있다고 기록한다.

---

# 13. 환경변수

`.env.example`에 최소한 다음 항목을 제공한다.

```env
POSTGRES_DB=investment
POSTGRES_USER=investment_user
POSTGRES_PASSWORD=change_me

DATABASE_URL=postgresql+psycopg://investment_user:change_me@postgres:5432/investment

NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
INTERNAL_API_BASE_URL=http://api:8000

WORKER_POLL_INTERVAL_SECONDS=2

N8N_HOST=localhost
N8N_PORT=5678
N8N_PROTOCOL=http
N8N_ENCRYPTION_KEY=change_me
```

실제 `.env`는 Git에 포함하지 않는다.

---

# 14. DB Migration

SQLAlchemy 모델을 정의하고 Alembic migration을 사용한다.

필수 구현:

```text
초기 migration 생성
jobs 테이블 생성
job_logs 테이블 생성
imports 테이블 생성
외래키 및 인덱스 생성
```

인덱스 예시:

```text
jobs(status, created_at)
job_logs(job_id, created_at)
imports(job_id)
```

애플리케이션 시작 시 자동으로 테이블을 생성하지 않는다.

DB 변경은 Alembic migration으로 관리한다.

---

# 15. 오류 처리

다음 오류를 처리한다.

* 지원하지 않는 파일 확장자
* 빈 CSV
* 필수 헤더 누락
* CSV 파싱 실패
* DB 연결 실패
* Worker 처리 실패
* 존재하지 않는 job_id
* 저장 경로 생성 실패

FastAPI 오류 응답 형식을 통일한다.

```json
{
  "error": {
    "code": "INVALID_CSV",
    "message": "Required CSV columns are missing.",
    "details": {
      "missing_columns": ["ticker"]
    }
  }
}
```

내부 오류 스택을 프론트엔드에 그대로 노출하지 않는다.

---

# 16. 테스트 요구사항

## Backend

* health API 테스트
* job 생성 테스트
* job 조회 테스트
* CSV 업로드 테스트
* 잘못된 CSV 테스트
* Worker 성공 처리 테스트
* Worker 실패 처리 테스트

## Frontend

최소한 다음 상태를 화면에서 처리한다.

* 로딩
* 성공
* 빈 목록
* API 연결 실패
* 작업 실패

## Integration

다음 흐름을 확인하는 통합 테스트 또는 실행 스크립트를 작성한다.

```text
작업 생성
→ Worker 처리
→ SUCCESS 확인
```

---

# 17. README 요구사항

README에는 다음 내용을 포함한다.

1. 프로젝트 목적
2. 전체 구조
3. 사전 설치 프로그램
4. WSL2에서 프로젝트를 실행하는 방법
5. `.env` 생성 방법
6. Docker Compose 실행 방법
7. DB migration 방법
8. Next.js 접속 주소
9. FastAPI 문서 주소
10. n8n 접속 주소
11. CSV 테스트 방법
12. 로그 확인 방법
13. 서비스 종료 방법
14. 데이터 초기화 시 주의사항

실행 명령 예시:

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
docker compose ps
```

로그 확인:

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f n8n
```

종료:

```bash
docker compose down
```

데이터 삭제 위험 명령:

```bash
docker compose down -v
```

이 명령은 PostgreSQL과 n8n 데이터를 삭제할 수 있다는 경고를 README에 명시한다.

---

# 18. 구현하지 말아야 할 것

이번 단계에서는 다음 기능을 추가하지 않는다.

```text
실제 증권사 API
실제 계좌 테이블
보유 종목 계산
뉴스 크롤링
공시 수집
가격 데이터 수집
Parquet
DuckDB
Redis
Celery
Kafka
Elasticsearch
MinIO
AI
RAG
백테스트
퀀트 지표
자동매매
로그인 시스템
클라우드 배포
```

필요 이상의 추상화, 마이크로서비스 분리, 이벤트 기반 아키텍처도 적용하지 않는다.

---

# 19. 완료 조건

다음 조건을 모두 만족하면 초기 구현이 완료된 것으로 본다.

```text
docker compose up -d로 전체 서비스가 실행된다.

localhost:3000에서 Next.js 화면이 열린다.

localhost:8000/docs에서 FastAPI 문서를 볼 수 있다.

localhost:5678에서 n8n이 열린다.

Next.js에서 테스트 작업을 생성할 수 있다.

생성된 작업이 PostgreSQL에 PENDING으로 저장된다.

Worker가 작업을 처리하고 SUCCESS 또는 FAILED로 변경한다.

Next.js에서 작업 상태와 로그를 확인할 수 있다.

CSV 파일을 업로드할 수 있다.

Worker가 CSV를 검증하고 처리 결과를 저장한다.

n8n에서 FastAPI 내부 작업 API를 호출할 수 있다.

컨테이너 재시작 후에도 PostgreSQL과 n8n 데이터가 유지된다.

README만 보고 새 환경에서 실행할 수 있다.
```

---

# 20. 개발 시 우선순위

```text
1. Docker Compose와 DB 연결
2. Alembic migration
3. FastAPI 작업 API
4. PostgreSQL 기반 Worker
5. Next.js 작업 목록
6. CSV 업로드
7. n8n 연결
8. 오류 처리
9. 테스트
10. README
```

화면 디자인보다 전체 흐름의 안정성을 우선한다.

초기 UI는 깔끔하고 단순하게 구성하되, 향후 메뉴와 기능을 확장할 수 있는 사이드바 기반 레이아웃으로 구현한다.
