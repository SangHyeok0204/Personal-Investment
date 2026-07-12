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

## 15. 키움 REST API 연동

키움증권 **REST API**로 계좌·잔고·보유종목을 불러와 대시보드 첫 화면(`/`)의 포트폴리오 영역에 표시한다. (키움 **OpenAPI+**는 Windows 전용 COM 컴포넌트라 Linux 컨테이너에서 직접 구동할 수 없어 REST 방식을 쓴다.) 키를 넣지 않아도 화면과 작업 파이프라인은 모두 동작하며, 동기화만 "키 미설정" 상태로 깨끗하게 실패한다.

### 1) 키 발급

키움증권 홈페이지 → **Open API** → **REST API** 사용 신청 후 `APP KEY`와 `SECRET KEY`를 발급받는다.

### 2) `.env`에 키 입력

`.env`에 아래 값을 채운다 (`.env.example` 참고). `KIWOOM_APP_KEY`/`KIWOOM_SECRET_KEY`만 발급값으로 바꾸면 되고, 나머지는 기본값을 그대로 둔다.

```env
KIWOOM_APP_KEY=발급받은_APP_KEY
KIWOOM_SECRET_KEY=발급받은_SECRET_KEY
KIWOOM_API_BASE_URL=https://api.kiwoom.com
KIWOOM_ENVIRONMENT=REAL

INTERNAL_API_KEY=change_me_internal   # 내부 API 인증 키(임의의 강한 값 권장). n8n·통합테스트와 값이 같아야 한다
```

**이미 `.env`가 있는 경우** — 이번 라운드에서 키가 5개(KIWOOM_* 4개 + `INTERNAL_API_KEY`) 새로 생겼다. 기존 `.env`에는 없으므로 `.env.example`을 보고 누락된 키를 이어붙여야 한다. 아래 한 줄이면 `.env.example`에는 있지만 `.env`에는 없는 키만 추가한다(값이 채워진 기존 키는 건드리지 않는다):

```bash
awk -F= 'NR==FNR{if($1 ~ /^[A-Z]/)seen[$1]=1; next} /^[A-Z]/ && !($1 in seen){print}' .env .env.example >> .env
```

이후 `.env`를 열어 `KIWOOM_APP_KEY`/`KIWOOM_SECRET_KEY`에 실제 발급값을 채운다.

### 3) 서비스 재기동

새 환경변수를 컨테이너에 반영한다.

```bash
docker compose up -d --force-recreate api worker n8n
```

(스키마가 아직이면 `docker compose exec api alembic upgrade head`로 마이그레이션을 먼저 끝낸다.)

### 4) 동기화 실행

http://localhost:3000 (대시보드 `/`) 상단 포트폴리오 영역에서 **[키움 계좌 동기화]** 버튼을 누른다. 작업이 PENDING → RUNNING → SUCCESS로 끝나면 요약 카드와 보유종목 테이블이 채워진다.

### 5) 문제 확인

- 동기화가 실패하면 대시보드 **Data Operations**의 해당 작업 로그(단계별 `step`과 오류 메시지)를 확인한다.
- 키 미설정 시 오류 메시지는 `KIWOOM_APP_KEY/KIWOOM_SECRET_KEY is not configured`이다 — `.env` 입력과 서비스 재기동을 다시 확인한다.
- n8n `Sync Kiwoom Portfolio` 워크플로에서 401이 나면 `.env`의 `INTERNAL_API_KEY`가 api·n8n 양쪽에 동일하게 반영됐는지 확인한다.

### 보안 주의

- APP/SECRET 키와 발급되는 액세스 토큰은 **`.env`와 메모리에만** 둔다. 토큰은 디스크·DB·로그에 기록되지 않는다.
- `.env`는 **Git에 커밋하지 않는다.** 로그와 원본 응답 저장 파일에는 appkey/secret/token/전체 계좌번호가 남지 않도록 되어 있다.

## 16. 자동 동기화 켜기 (자산 추이 차트 채우기)

대시보드의 **자산 추이 차트**는 동기화할 때마다 찍히는 스냅샷으로 그린다. 스냅샷은 **동기화한 그 순간에만** 생기고 과거 이력은 소급 생성할 수 없다(키움 잔고 조회는 현재 상태만 준다). 따라서 **자동 동기화를 켜 두어야 하루 한 점씩 쌓이면서 차트가 의미를 갖는다.** 켜기 전까지는 점이 부족해 차트 대신 "축적 중" 안내가 표시된다.

> **차트에 점이 찍히는 규칙**: 동기화 1회 = 스냅샷 1개지만, **차트는 하루에 1점**만 그린다 — 그날의 **마지막** 동기화 값이다. 아래 스케줄은 평일에 2번(06:30·16:10) 도는데 둘 다 같은 날이므로 평일 점은 16:10 값 하나다. 하루에 여러 번 수동 동기화해도 그날 점은 여전히 1개다. (점이 동기화 횟수만큼 안 늘어난다고 고장난 게 아니다.)

### 1) 스케줄 워크플로 import

```bash
docker compose exec n8n n8n import:workflow --input=/workflows/portfolio/sync-kiwoom-portfolio-scheduled.json
```

또는 n8n UI(http://localhost:5678) → **Import from File** → `workflows/n8n/portfolio/sync-kiwoom-portfolio-scheduled.json` 선택.

### 2) 활성화 (직접 켜야 한다)

**import만으로는 돌지 않는다.** 워크플로는 `"active": false` 상태로 들어온다 — 사용자가 모르는 사이에 외부 API를 주기적으로 호출하지 않도록 일부러 꺼 둔 것이다.

1. http://localhost:5678 접속
2. `Sync Kiwoom Portfolio (Scheduled)` 워크플로를 연다
3. 우측 상단 **Active** 토글을 켠다 (끄고 싶으면 같은 토글을 내린다)

### 3) 실행 시각

| 크론 | 시각 (KST) | 목적 |
|---|---|---|
| `10 16 * * 1-5` | 평일 16:10 | 국내장 마감 후 종가 반영 |
| `30 6 * * *` | 매일 06:30 | 미국장 마감 후 반영 (서머타임 양쪽 커버) |

compose의 `GENERIC_TIMEZONE=Asia/Seoul`과 워크플로 `settings.timezone` 덕분에 크론은 **KST 기준**이다. 실행 이력과 실패는 n8n **Executions** 화면에서 확인한다. 동기화 작업은 멱등이라 트리거가 겹쳐도 중복 적재되지 않는다.

먼저 **[키움 계좌 동기화]** 버튼으로 수동 동기화가 성공하는지(키가 유효한지) 확인한 뒤 켜는 것을 권장한다. 자세한 내용은 `workflows/n8n/README.md` 참고.

### 4) 안전: 읽기 전용 (주문 없음)

스케줄이 돌리는 `SYNC_KIWOOM_PORTFOLIO` 작업은 키움 REST API의 **조회 TR만** 호출한다 — 계좌·잔고·보유종목·예수금을 **읽기만** 한다. **주문(매수/매도)·이체 기능은 아예 구현되어 있지 않다.** 자동 동기화를 켜 두어도 계좌에서 거래가 발생하지 않는다.

다만 켜는 순간부터 **실제 증권사 API를 주기적으로 호출**하게 되므로(그래서 import만으로는 켜지지 않게 해 두었다), 위 시각과 호출 내용을 확인한 뒤 직접 Active를 켜는 것이다.
