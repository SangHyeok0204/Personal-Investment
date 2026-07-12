# 개인 투자 대시보드 프로젝트 설계서

## 1. 프로젝트 개요

이 프로젝트는 개인 투자자가 집에서 자신의 포트폴리오를 직접 관리하고, 계좌 현황·투자 정보·데이터 수집·분석 결과·투자 판단 기록을 하나의 로컬 시스템에서 운영하기 위한 개인 투자 플랫폼이다.

초기 단계에서는 집 PC의 `localhost` 환경에서만 실행하며, 외부 서버 배포와 자동매매는 포함하지 않는다.

프로젝트의 목표는 단순한 시각화 대시보드가 아니라 다음 기능을 결합한 개인 투자 운영 시스템을 구축하는 것이다.

- 계좌 및 자산 데이터 관리
- 뉴스·공시·시장 데이터 수집
- 데이터 정제 및 저장
- 투자 분석 기능
- 투자 아이디어 및 의사결정 기록
- 데이터 파이프라인 실행 상태 확인
- 향후 퀀트 분석, AI, 리밸런싱 기능 확장

---

## 2. 프로젝트의 기본 방향

### 2.1 초기 운영 범위

- Windows PC에서 실행
- WSL2 기반 Linux 개발환경 사용
- Docker Desktop 사용
- 브라우저에서 대시보드 접속
- 브라우저에서 n8n 워크플로 확인
- PostgreSQL은 로컬 Docker 컨테이너에서 실행
- 데이터는 사용자 PC에 저장
- 외부 서버 및 클라우드 DB는 초기 단계에서 사용하지 않음
- 자동매매 기능은 제외
- 구체적인 투자 지표 및 전략은 추후 결정

### 2.2 핵심 설계 원칙

```text
UI와 데이터 처리 로직을 분리한다.
대시보드가 DB에 직접 접근하지 않는다.
n8n은 작업 순서와 실행 상태를 관리한다.
Python은 실제 데이터 처리와 분석을 담당한다.
원본 데이터와 가공 데이터를 분리한다.
운영 데이터와 대규모 시계열 데이터를 분리한다.
모든 데이터 수집 작업은 실행 이력을 남긴다.
```

---

## 3. 전체 시스템 아키텍처

```text
┌─────────────────────────────────────────────┐
│                 Web Browser                 │
│                                             │
│ localhost:3000  개인 투자 대시보드          │
│ localhost:5678  n8n 파이프라인 관리         │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│              Next.js Frontend               │
│                                             │
│ Overview / Portfolio / Research / Analysis  │
│ Decisions / Data Operations / Settings      │
└─────────────────────┬───────────────────────┘
                      │ REST API
                      ▼
┌─────────────────────────────────────────────┐
│               FastAPI Backend               │
│                                             │
│ 계좌 / 자산 / 문서 / 데이터 / 작업 API      │
│ 업무 규칙 / 검증 / DB 접근                  │
└──────────────┬─────────────────┬────────────┘
               │                 │
               ▼                 ▼
      ┌────────────────┐  ┌──────────────────┐
      │ PostgreSQL     │  │ Parquet Storage  │
      │ 운영 데이터    │  │ 시계열·대용량 데이터 │
      └────────────────┘  └─────────┬────────┘
                                    ▼
                               DuckDB 분석

┌─────────────────────────────────────────────┐
│                    n8n                      │
│                                             │
│ 트리거 / 데이터 수집 / 작업 순서 / 분기     │
│ 재시도 / 오류 처리 / 실행 이력 확인         │
└─────────────────────┬───────────────────────┘
                      ▼
┌─────────────────────────────────────────────┐
│               Python Worker                 │
│                                             │
│ 크롤링 / 정제 / 변환 / 적재 / 분석 / 백업   │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│              Docker Compose                 │
│                                             │
│ web / api / worker / postgres / n8n         │
└─────────────────────────────────────────────┘
```

---

## 4. 각 기술의 역할

## 4.1 Next.js

Next.js는 사용자가 직접 보는 웹 대시보드를 담당한다.

주요 역할:

- 페이지 구성
- 메뉴 및 레이아웃
- 계좌·보유자산·뉴스·작업 상태 화면
- 표와 차트
- 검색 및 필터
- 반응형 UI
- 향후 모바일 화면 대응
- 복잡한 사용자 인터랙션

권장 프론트엔드 구성:

```text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
TanStack Table
Zustand
Apache ECharts 또는 Plotly.js
React Hook Form
Zod
```

---

## 4.2 REST API

REST API는 프론트엔드와 백엔드가 데이터를 주고받는 방식이다.

예시:

```text
GET  /api/v1/accounts
GET  /api/v1/portfolio
GET  /api/v1/news
POST /api/v1/transactions
POST /api/v1/investment-ideas
```

요청 흐름:

```text
Next.js
  ↓ REST API 요청
FastAPI
  ↓ DB 조회 또는 업무 처리
PostgreSQL / Parquet
  ↓ 결과 반환
Next.js 화면 표시
```

---

## 4.3 FastAPI

FastAPI는 Python 기반 REST API 서버다.

역할:

- Next.js 요청 처리
- 입력값 검증
- 계좌·거래·뉴스·작업 관련 업무 로직
- PostgreSQL 조회 및 저장
- Worker 작업 생성
- n8n 내부 호출 처리
- API 문서 자동 생성

API 구분:

```text
/api/v1/*    대시보드가 사용하는 일반 API
/internal/*  n8n과 worker가 사용하는 내부 API
/system/*    시스템 상태 및 운영 API
```

예시:

```text
GET  /api/v1/portfolio/summary
GET  /api/v1/transactions
POST /api/v1/investment-ideas

POST /internal/jobs/import-account-file
POST /internal/jobs/collect-market-data
POST /internal/jobs/process-news

GET  /system/health
GET  /system/jobs
```

---

## 4.4 PostgreSQL

PostgreSQL은 초기에는 외부 DB를 빌리는 것이 아니라 로컬 PC에서 실행한다.

구조:

```text
Windows PC
└── Docker Desktop
    └── PostgreSQL Container
        └── Docker Volume
```

저장 대상:

- 계좌
- 거래 내역
- 입출금
- 현재 포지션
- 사용자 설정
- 관심 종목
- 투자 아이디어
- 뉴스 메타데이터
- 데이터 소스 정보
- 작업 실행 상태
- 오류 로그
- 데이터 품질 검사 결과

PostgreSQL 데이터는 Docker named volume에 저장한다.

```yaml
services:
  postgres:
    image: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

다음 명령은 데이터가 유지된다.

```bash
docker compose stop
docker compose start
```

다음 명령은 volume까지 삭제할 수 있으므로 주의해야 한다.

```bash
docker compose down -v
```

---

## 4.5 Parquet와 DuckDB

모든 데이터를 PostgreSQL에 넣지 않는다.

Parquet 저장 대상:

- 일별 가격
- 분봉 가격
- 거래량
- 시장 데이터
- 재무 데이터
- 대규모 크롤링 결과
- 백테스트용 데이터
- 분석용 시계열 데이터

DuckDB의 역할:

- Parquet 파일 조회
- 대규모 집계
- 분석용 SQL 실행
- 백테스트 데이터 조회
- 임시 데이터 분석

정리:

```text
PostgreSQL = 운영 데이터
Parquet    = 시계열·대용량 데이터
DuckDB     = Parquet 분석 엔진
```

---

## 4.6 n8n

n8n은 데이터 파이프라인의 시각적 설계 및 운영 도구다.

담당 영역:

- 스케줄 트리거
- API 호출
- 파일 수집 시작
- 뉴스·공시 수집 요청
- 작업 순서 연결
- 성공·실패 분기
- 재시도
- 오류 알림
- FastAPI 호출
- 후속 작업 연결
- 실행 이력 확인
- 수동 테스트

원칙:

```text
n8n = 언제, 어떤 순서로 실행할지
Python = 실제로 무엇을 처리하고 계산할지
```

n8n 안에 복잡한 금융 계산이나 대규모 pandas 로직을 작성하지 않는다.

예시 흐름:

```text
Schedule Trigger
      ↓
보유 종목 조회 API
      ↓
뉴스 수집 작업 생성
      ↓
Python Worker 실행
      ↓
Raw 데이터 저장
      ↓
정제 작업
      ↓
DB 적재
   ↙        ↘
성공         실패
 ↓            ↓
상태 기록     오류 기록
```

---

## 4.7 Python Worker

Worker는 장시간 실행되는 작업을 담당한다.

담당 업무:

- 계좌 파일 읽기
- CSV·Excel 파싱
- 외부 API 수집
- 뉴스 크롤링
- 데이터 정제
- 종목 코드 매핑
- 중복 제거
- PostgreSQL 적재
- Parquet 생성
- 백업
- 분석 작업

작업 흐름:

```text
n8n
 ↓
FastAPI에 작업 생성 요청
 ↓
jobs 테이블에 PENDING 등록
 ↓
Worker 실행
 ↓
RUNNING
 ↓
처리 및 저장
 ↓
SUCCESS 또는 FAILED
```

---

## 4.8 Docker Compose

Docker Compose는 프로젝트의 모든 서비스를 로컬에서 함께 실행한다.

초기 서비스:

```text
web       Next.js
api       FastAPI
worker    Python Worker
postgres  PostgreSQL
n8n       Workflow Orchestration
```

향후 추가 가능:

```text
redis
minio
elasticsearch
ollama
prometheus
grafana
```

초기에는 위 확장 서비스를 넣지 않는다.

---

## 5. 대시보드 UI 구조

구체적인 지표는 지금 결정하지 않고, 업무 영역을 기준으로 화면을 구성한다.

## 5.1 전체 메뉴

```text
Overview

Portfolio
├── Accounts
├── Holdings
├── Transactions
└── Cash Management

Research
├── News
├── Disclosures
├── Documents
├── Watchlist
└── Search

Analysis
├── Portfolio
├── Assets
├── Market
├── Strategies
└── Experiments

Decisions
├── Investment Ideas
├── Trade Plans
├── Journal
└── Reviews

Data Operations
├── Pipeline Overview
├── Data Sources
├── Import History
├── Data Quality
├── Job History
└── System Logs

Settings
├── Accounts
├── Sources
├── Classifications
├── Schedules
└── System
```

---

## 5.2 화면별 역할

### Overview

전체 투자 시스템의 요약 화면이다.

- 전체 상태 요약
- 최근 변화
- 데이터 갱신 상태
- 경고 항목
- 최근 투자 활동
- 주요 정보 진입점

### Portfolio

개인 자산과 거래를 관리한다.

- 계좌
- 보유 자산
- 거래 내역
- 현금 흐름
- 입출금
- 포트폴리오 구성

### Research

비정형 투자 정보를 관리한다.

- 뉴스
- 공시
- 리서치 문서
- 관심 종목
- 검색
- 향후 AI 요약 및 RAG 연결

### Analysis

투자 분석 기능이 들어가는 영역이다.

- 포트폴리오 분석
- 개별 자산 분석
- 시장 분석
- 퀀트 분석
- 백테스트
- 실험

구체적인 지표와 전략은 추후 결정한다.

### Decisions

사용자의 실제 투자 판단을 기록한다.

- 투자 아이디어
- 매수·매도 계획
- 투자 논리
- 투자 일지
- 사후 평가
- 검토 기록

### Data Operations

데이터 파이프라인과 시스템 상태를 확인한다.

- 실행 중인 작업
- 최근 성공·실패 작업
- 데이터 소스 상태
- 마지막 갱신 시간
- 데이터 품질
- 오류 로그
- n8n 워크플로 링크

### Settings

시스템 설정을 관리한다.

- 계좌 설정
- 데이터 소스
- 스케줄
- 분류 기준
- 시스템 설정
- 백업 설정

---

## 6. 프로젝트 폴더 구조

```text
personal-investment-platform/
│
├── apps/
│   ├── web/
│   ├── api/
│   └── worker/
│
├── packages/
│   ├── ui/
│   ├── api-client/
│   ├── shared-types/
│   └── config/
│
├── services/
│   ├── portfolio/
│   ├── market-data/
│   ├── research/
│   ├── analytics/
│   └── data-quality/
│
├── workflows/
│   └── n8n/
│
├── database/
│   ├── migrations/
│   ├── seeds/
│   ├── schemas/
│   └── backups/
│
├── storage/
│   ├── raw/
│   ├── staging/
│   ├── curated/
│   ├── analytics/
│   ├── documents/
│   └── exports/
│
├── infrastructure/
│   ├── docker/
│   ├── postgres/
│   ├── n8n/
│   └── monitoring/
│
├── scripts/
│   ├── setup/
│   ├── import/
│   ├── backup/
│   └── maintenance/
│
├── docs/
│   ├── architecture/
│   ├── database/
│   ├── workflows/
│   ├── ui/
│   └── adr/
│
├── tests/
│   ├── backend/
│   ├── frontend/
│   ├── integration/
│   └── data-quality/
│
├── docker-compose.yml
├── .env
├── .env.example
├── Makefile
└── README.md
```

---

## 7. 프론트엔드 폴더 구조

```text
apps/web/
│
├── app/
│   ├── (dashboard)/
│   │   ├── overview/
│   │   ├── portfolio/
│   │   ├── research/
│   │   ├── analysis/
│   │   ├── decisions/
│   │   ├── data-ops/
│   │   └── settings/
│   │
│   ├── layout.tsx
│   ├── loading.tsx
│   ├── error.tsx
│   └── page.tsx
│
├── components/
│   ├── layout/
│   ├── navigation/
│   ├── charts/
│   ├── tables/
│   ├── forms/
│   ├── feedback/
│   └── domain/
│
├── features/
│   ├── portfolio/
│   ├── research/
│   ├── analysis/
│   ├── decisions/
│   └── data-ops/
│
├── hooks/
├── stores/
├── lib/
├── styles/
└── types/
```

구분 원칙:

```text
components = 범용 UI
features   = 특정 업무 기능
app        = 페이지와 라우팅
```

---

## 8. 백엔드 폴더 구조

```text
apps/api/
│
├── app/
│   ├── api/
│   │   ├── portfolio/
│   │   ├── research/
│   │   ├── analysis/
│   │   ├── decisions/
│   │   ├── data_ops/
│   │   └── internal/
│   │
│   ├── core/
│   ├── dependencies/
│   ├── middleware/
│   └── main.py
│
└── tests/
```

도메인별 서비스 구조:

```text
services/portfolio/
├── domain/
├── application/
├── repositories/
├── schemas/
└── tests/
```

역할:

```text
domain       핵심 투자 개념
application  업무 흐름
repositories DB 접근
schemas      요청·응답 형식
tests        도메인별 테스트
```

---

## 9. Worker 폴더 구조

```text
apps/worker/
├── tasks/
│   ├── ingestion/
│   ├── processing/
│   ├── analytics/
│   ├── exports/
│   └── maintenance/
│
├── runners/
├── clients/
└── main.py
```

---

## 10. n8n 워크플로 저장 구조

n8n UI에서 만든 워크플로는 JSON으로 export하여 Git에 저장한다.

```text
workflows/n8n/
├── account/
│   ├── import-account-file.json
│   └── sync-broker-account.json
│
├── market/
│   ├── daily-market-update.json
│   └── fx-update.json
│
├── research/
│   ├── collect-news.json
│   └── collect-disclosures.json
│
├── maintenance/
│   ├── daily-backup.json
│   └── data-quality-check.json
│
└── README.md
```

각 워크플로 문서에 기록할 내용:

- 목적
- 트리거
- 입력
- 출력
- 호출 API
- 실패 처리
- 재시도 정책
- 관련 DB 테이블
- 담당 Python 작업

---

## 11. 데이터 저장 계층

데이터는 다음 단계로 나눈다.

```text
Raw → Staging → Curated → Analytics
```

### Raw

외부에서 받은 원본 그대로 저장한다.

- API 원본 응답
- CSV
- Excel
- 뉴스 원문
- 공시 원문
- HTML
- PDF

원칙적으로 수정하지 않는다.

### Staging

가공 전 임시 정제 단계다.

- 컬럼명 정리
- 자료형 변환
- 중복 확인
- 날짜 변환
- 종목 코드 매핑
- 결측값 확인

### Curated

시스템 전체에서 공통으로 사용하는 표준 데이터다.

- 표준 거래 데이터
- 표준 종목 마스터
- 정제 가격 데이터
- 정제 뉴스 데이터
- 표준 계좌 데이터

### Analytics

분석 및 화면 표시용 결과다.

- 포트폴리오 스냅샷
- 집계 결과
- 분석 결과
- 리포트 데이터
- 대시보드 캐시

---

## 12. PostgreSQL 스키마 구성

```text
core
portfolio
market
research
decision
operations
```

### core

공통 기준정보:

```text
assets
asset_identifiers
exchanges
currencies
brokers
data_sources
```

### portfolio

개인 자산 및 거래:

```text
accounts
transactions
cash_flows
positions
portfolio_snapshots
```

### market

시장 데이터 관리정보:

```text
price_series_metadata
corporate_actions
market_calendars
data_versions
```

대규모 가격 데이터 자체는 Parquet에 저장할 수 있다.

### research

뉴스 및 문서:

```text
news_articles
disclosures
documents
document_entities
tags
```

### decision

투자 의사결정:

```text
watchlists
investment_ideas
decision_logs
trade_plans
journal_entries
```

### operations

시스템 운영:

```text
jobs
job_runs
job_steps
job_errors
data_quality_checks
import_history
error_logs
```

---

## 13. DB 설계 원칙

### 13.1 거래 내역이 기준 데이터

```text
Transaction = 원천 사실
Position    = 거래를 기반으로 계산된 현재 상태
```

포지션은 필요하면 거래 데이터로 다시 생성할 수 있어야 한다.

### 13.2 외부 종목 코드와 내부 ID 분리

```text
내부 asset_id: 1024

KRX:      000660
Yahoo:    000660.KS
증권사:   A000660
Reuters:  000660.KS
```

이를 위해 `asset_identifiers` 테이블을 둔다.

```text
asset_id
source
identifier_type
identifier_value
valid_from
valid_to
```

### 13.3 출처 기록

모든 주요 데이터는 출처를 기록한다.

```text
source_id
source_record_id
collected_at
effective_at
import_batch_id
```

### 13.4 시간과 통화 명시

```text
currency
exchange
timezone
observed_at
```

DB 시간은 UTC 저장을 기본으로 하고, 화면에서는 한국 시간으로 변환한다.

### 13.5 수정 이력 유지

```text
created_at
updated_at
created_by
source
import_batch_id
```

중요한 데이터는 수정 이력을 남긴다.

### 13.6 삭제보다 비활성화

```text
is_active
deleted_at
```

---

## 14. 작업 실행 관리

모든 파이프라인 실행은 DB에 기록한다.

### job_runs

```text
id
workflow_name
external_execution_id
status
trigger_type
started_at
finished_at
records_read
records_written
error_count
created_at
```

### job_steps

```text
id
job_run_id
step_name
status
started_at
finished_at
message
metadata_json
```

이 구조를 통해 다음 내용을 확인할 수 있다.

- 오늘 데이터가 갱신됐는가
- 어느 소스가 실패했는가
- 마지막 정상 수집 시간은 언제인가
- 몇 건을 읽고 몇 건을 저장했는가
- 어느 단계에서 오류가 발생했는가

---

## 15. 데이터 품질 관리

검사 대상:

- 필수 컬럼 누락
- 중복 행
- 잘못된 날짜
- 음수 가격
- 통화 누락
- 알 수 없는 종목 코드
- 비정상적 값 변화
- 데이터 수집 공백

검사 수준:

```text
Critical = DB 반영 중단
Warning  = 반영하되 경고 표시
Info     = 기록만 저장
```

---

## 16. Windows 개발환경

권장 구성:

```text
Windows 11
├── Docker Desktop
│   └── WSL2 backend
├── WSL2
│   └── Ubuntu
├── VS Code
│   └── WSL Extension
└── Browser
    ├── localhost:3000
    └── localhost:5678
```

프로젝트 위치:

```bash
/home/사용자명/projects/personal-investment-platform
```

권장하지 않는 위치:

```text
C:\Users\사용자명\Desktop\project
/mnt/c/Users/사용자명/Desktop/project
```

이유:

- Next.js 파일 변경 감지 속도 저하
- node_modules 성능 저하
- Docker bind mount 성능 저하
- Linux 권한 문제
- Git 파일 처리 문제

VS Code 실행:

```bash
cd ~/projects/personal-investment-platform
code .
```

---

## 17. Docker 네트워크와 포트

### 외부 접근 포트

```text
3000  Next.js
5678  n8n
```

개발 중 필요 시:

```text
8000  FastAPI
5432  PostgreSQL
```

### 컨테이너 간 통신

```text
Next.js → http://api:8000
n8n     → http://api:8000
FastAPI → postgresql://postgres:5432
```

컨테이너 안에서 `localhost`는 자기 자신을 의미한다.

잘못된 예:

```text
http://localhost:8000
```

올바른 예:

```text
http://api:8000
```

---

## 18. 로컬 저장 전략

```text
소스 코드
→ WSL2 Linux 파일시스템

PostgreSQL 데이터
→ Docker named volume

n8n 설정과 credentials
→ Docker named volume

CSV·PDF·Parquet
→ 프로젝트 storage 폴더

백업
→ Windows 드라이브 또는 외장 디스크
```

예시:

```yaml
services:
  postgres:
    volumes:
      - postgres_data:/var/lib/postgresql/data

  n8n:
    volumes:
      - n8n_data:/home/node/.n8n
      - ./storage:/files

volumes:
  postgres_data:
  n8n_data:
```

---

## 19. 백업 전략

백업 대상:

- PostgreSQL dump
- n8n 워크플로
- n8n 설정
- Parquet 데이터
- 투자 일지
- 원본 파일
- 설정 파일
- 문서 및 뉴스 원문

권장 주기:

```text
매일 증분 백업
매주 전체 백업
외장 저장장치 또는 별도 암호화 폴더 복사
```

---

## 20. 초기 Docker Compose 구성

```text
services:
  web
  api
  worker
  postgres
  n8n
```

초기에는 다음 서비스는 제외한다.

```text
redis
minio
elasticsearch
ollama
prometheus
grafana
```

필요성이 명확해질 때 추가한다.

---

## 21. 초기 개발 순서

### Phase 1. 인프라 골격

```text
Monorepo 생성
Next.js 실행
FastAPI 실행
PostgreSQL 실행
n8n 실행
Docker Compose 연결
```

### Phase 2. 수직 슬라이스

가장 먼저 다음 흐름을 구현한다.

```text
n8n 버튼 클릭
→ FastAPI 작업 생성
→ Worker 작업 실행
→ PostgreSQL 상태 갱신
→ Next.js에서 진행 상태 확인
```

### Phase 3. 파일 수집 파이프라인

```text
파일 업로드
→ Raw 저장
→ 작업 등록
→ Worker 정제
→ DB 반영
→ 처리 결과 표시
```

### Phase 4. 첫 번째 실제 도메인

```text
계좌
거래
보유 자산
```

### Phase 5. 확장

```text
시장 데이터
뉴스
공시
문서
분석
투자 판단
AI
```

---

## 22. 최종 기술 결정안

```text
Frontend
Next.js + TypeScript

UI
Tailwind CSS + shadcn/ui

API
FastAPI

Background Processing
Python Worker

Workflow Orchestration
n8n

Operational Database
PostgreSQL

Time-series Storage
Parquet

Analytical Query
DuckDB

Infrastructure
Docker Compose

Development Environment
Windows + WSL2 + Docker Desktop
```

---

## 23. 각 계층의 책임 요약

```text
Next.js
사용자 화면과 상호작용

REST API
프론트엔드와 백엔드의 통신 방식

FastAPI
업무 규칙과 데이터 접근

Worker
장시간 데이터 처리와 분석

n8n
파이프라인 순서, 트리거, 분기, 실행 관찰

PostgreSQL
운영 상태와 관계형 데이터

Parquet
대규모 시계열 및 분석 데이터

DuckDB
Parquet 기반 분석

Docker Compose
전체 로컬 시스템 실행과 격리
```

---

## 24. 현재 단계에서 결정하지 않는 것

- 구체적인 성과 지표
- 퀀트 팩터
- 리스크 지표
- 백테스트 전략
- 뉴스 감성분석 방식
- AI 모델
- 리밸런싱 알고리즘
- 자동매매
- 외부 배포
- 모바일 앱

현재 단계의 목표는 기능 정의가 아니라 **확장 가능한 시스템 골격을 확정하는 것**이다.
