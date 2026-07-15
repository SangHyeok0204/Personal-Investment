# 개인 투자 플랫폼 (Personal Investment Platform)

Windows + WSL2 + Docker Desktop 환경에서 실행되는 로컬 개인 투자 플랫폼의 초기 골격이다.
이 단계의 목표는 투자 분석 기능이 아니라, 다음 수직 흐름이 처음부터 끝까지 동작하게 만드는 것이다.

```text
Next.js 화면에서 작업 실행
  -> FastAPI가 작업 생성
  -> PostgreSQL에 작업 상태 저장
  -> Python Worker가 작업 처리
  -> PostgreSQL 작업 상태 갱신
  -> Next.js에서 진행 결과 확인
```

n8n에서도 같은 FastAPI 내부 작업 생성 API(`POST /internal/jobs`)를 호출할 수 있다.

## 1. 목적

- 로컬에서 도는 작업 처리 파이프라인의 골격 구축 (job 생성 → worker 처리 → 상태 조회).
- 첫 실제 작업으로 CSV 업로드 및 검증을 구현한다 (실제 포트폴리오 적재는 다음 단계).
- 투자 지표, 뉴스 크롤링, 퀀트 분석, 백테스트, AI 기능은 이 단계에서 구현하지 않는다.

## 2. 전체 구조

```text
personal-investment-platform/
├── apps/
│   ├── web/         # Next.js 15 대시보드 (Overview / Data Operations / Settings)
│   ├── api/         # FastAPI + SQLAlchemy + Alembic
│   └── worker/      # PostgreSQL polling worker
├── database/
│   ├── migrations/  # Alembic 마이그레이션
│   └── seeds/
├── workflows/n8n/   # n8n 워크플로 (Create Test Job)
├── storage/
│   ├── raw/         # 업로드된 원본 CSV
│   └── processed/   # 검증·정규화된 CSV
├── scripts/         # 샘플 CSV, 통합 테스트 스크립트
├── docs/architecture/
├── docker-compose.yml
├── .env.example
├── Makefile
└── README.md
```

서비스 구성 (Docker Compose):

| 서비스 | 역할 | 외부 포트 |
|---|---|---|
| web | Next.js 대시보드 | 3000 |
| api | FastAPI 서버 | 8000 |
| worker | 작업 처리 프로세스 | (없음) |
| postgres | PostgreSQL 16 | 5432 |
| n8n | 워크플로 자동화 | 5678 |

컨테이너 내부 통신은 서비스 이름으로 한다 (`http://api:8000`, `postgres:5432`). `localhost`는 쓰지 않는다.

## 3. 사전 설치 프로그램

- Windows 10/11 + **WSL2** (Ubuntu)
- **Docker Desktop** — 설정에서 WSL2 backend 및 Ubuntu 통합을 켠다.
- `make` — 선택 사항 (Ubuntu: `sudo apt-get install -y make`). 없으면 아래 각 명령의 `docker compose ...` 원문을 직접 실행하면 된다.

Docker Desktop이 실행 중이어야 한다.

## 4. WSL2에서 실행하는 방법

WSL2 Ubuntu 셸에서 프로젝트 폴더로 이동한다. 이후 모든 명령은 이 폴더에서 실행한다.

```bash
cd ~/projects/personal-investment-platform
```

프로젝트는 WSL 파일시스템(`~/...`) 안에 두는 것이 빌드·실행이 빠르다.

## 5. `.env` 생성 방법

`.env.example`을 복사해 `.env`를 만든다. 실제 `.env`는 Git에 커밋하지 않는다.

```bash
cp .env.example .env
```

기본값으로 바로 실행할 수 있다. 운영 시에는 `POSTGRES_PASSWORD`와 `N8N_ENCRYPTION_KEY`를 반드시 바꾼다.

## 6. Docker Compose 실행 방법

```bash
make build     # docker compose build
make up        # docker compose up -d
make ps        # docker compose ps
```

모든 서비스가 healthy가 될 때까지 기다린다. (`make ps`로 상태 확인)

## 7. DB Migration 방법

컨테이너 기동 후 최초 1회, 이후 스키마 변경 시마다 실행한다. 애플리케이션은 시작 시 테이블을 자동 생성하지 않으며, 스키마는 Alembic 마이그레이션으로만 관리한다.

```bash
make migrate   # docker compose exec api alembic upgrade head
```

## 8. Next.js 접속 주소

http://localhost:3000

## 9. FastAPI 문서 주소

http://localhost:8000/docs (Swagger UI)

## 10. n8n 접속 주소

http://localhost:5678

### n8n 워크플로 import

`Create Test Job` 워크플로(`workflows/n8n/create-test-job.json`)를 n8n에 등록하는 방법은 두 가지다.

- **UI**: http://localhost:5678 접속 → 우측 상단 메뉴 → **Import from File** → `workflows/n8n/create-test-job.json` 선택.
- **CLI** (`./workflows/n8n`가 컨테이너의 `/workflows`로 마운트되어 있다):

  ```bash
  docker compose exec n8n n8n import:workflow --input=/workflows/create-test-job.json
  ```

import 후 워크플로를 열고 **Execute Workflow**를 누르면 `POST /internal/jobs`로 테스트 작업이 생성된다. 자세한 내용은 `workflows/n8n/README.md` 참고.

## 11. CSV 테스트 방법

### 화면에서
1. http://localhost:3000 → **Data Operations** 로 이동
2. **Run Test Job** 버튼으로 테스트 작업 실행 → 상태가 PENDING → RUNNING → SUCCESS 로 바뀌는지 확인
3. CSV 업로드 영역에 `scripts/sample-holdings.csv` 업로드 → 작업 상세에서 로그와 결과 확인

### 명령줄에서 (통합 테스트)
전체 흐름(health → 작업 생성 → worker 처리 → SUCCESS → CSV 업로드 → stats)을 한 번에 검증한다. 저장소 루트에서 실행한다.

```bash
make integration    # bash scripts/integration-test.sh
```

마지막에 `ALL INTEGRATION TESTS PASSED` 가 출력되면 성공이다.

### 샘플 CSV (`scripts/sample-holdings.csv`)

```csv
account_name,ticker,asset_name,quantity
Main Account,000660,SK Hynix,10
Main Account,005930,Samsung Electronics,20
```

필수 헤더는 `account_name,ticker,asset_name,quantity` 이다. worker가 헤더·행·`quantity` 값을 검증한 뒤 정규화 결과를 `storage/processed/` 에 저장한다.

## 12. 로그 확인 방법

```bash
make logs                     # 전체 서비스 로그 follow
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f n8n
```

## 13. 서비스 종료 방법

```bash
make down      # docker compose down  (컨테이너만 제거, 데이터 볼륨은 유지)
```

## 14. 데이터 초기화 시 주의사항

```bash
make clean     # docker compose down -v
```

**경고:** `docker compose down -v` 는 named volume(`postgres_data`, `n8n_data`)을 삭제한다. PostgreSQL의 모든 작업 기록과 n8n의 모든 워크플로·자격증명이 사라지며 되돌릴 수 없다.

- 컨테이너 재시작(`down` 후 다시 `up`)만으로는 데이터가 유지된다. 데이터가 지워지는 것은 `-v`를 붙였을 때뿐이다.
- `.env`의 `POSTGRES_*`를 바꿨는데 이미 `postgres_data` 볼륨이 만들어져 있으면 새 자격증명이 반영되지 않는다. 이 경우에도 볼륨 삭제(`down -v`) 후 재기동이 필요하다.

## 운영 시 참고

- 개발 편의를 위해 PostgreSQL 포트(5432)를 외부로 열어 두었다. 운영 환경에서는 `docker-compose.yml`의 postgres `ports` 항목을 제거해 외부 노출을 막을 수 있다.
- 비밀번호·암호화 키는 `.env`에만 두고 코드·이미지에 하드코딩하지 않는다.
