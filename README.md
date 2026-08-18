# 개인 투자 플랫폼 (Personal Investment Platform)

Windows + WSL2 + Docker Desktop 환경에서 실행되는 로컬 개인 투자 플랫폼이다.
2026-07 에 작업(job) 파이프라인 골격으로 시작해, 지금은 사내 리포트·모니터링 화면 십여 개를
얹은 대시보드로 쓰고 있다. 골격은 그대로다 — 백그라운드 일은 전부 작업 하나로 수렴한다.

```text
Next.js 화면에서 작업 실행
  -> FastAPI가 작업 생성
  -> PostgreSQL에 작업 상태 저장
  -> Python Worker가 작업 처리
  -> PostgreSQL 작업 상태 갱신
  -> Next.js에서 진행 결과 확인
```

여기에 두 갈래가 더 붙어 있다.

- **collector** — S: 공유 폴더의 레거시 엔진·데이터를 그대로 임포트해 계산하는 별도 서비스
  (ETF iNAV · WRAP · LP평가 · 성과분석 · 13F · 매크로 · 텔레그램 뉴스). job 파이프라인을 거치지
  않고 api 가 프록시해 부른다. `profiles: ["collector"]` 게이트라 최초 1회는 프로필을 켜서 띄운다.
- **n8n** — 스케줄 자동화. `POST /internal/jobs` 로 작업을 만들기도 하고, collector 를 직접
  부르기도 하고(`/perf-report/generate`), 윈도우 PC 에 파일 드롭으로 일을 넘기기도 한다
  (`storage/trigger`). 자세한 건 `workflows/n8n/README.md`.

## 1. 목적

- 로컬에서 도는 작업 처리 파이프라인 (job 생성 → worker 처리 → 상태 조회).
- 사내 리포트·모니터링을 한 화면에 모으기 (iNAV · WRAP · 성과분석 · 매크로 · 텔레그램 뉴스 등).
- 손으로 돌리던 리포트 생성을 스케줄로 대체하기 (성과분석 · 주간가격모니터 · 매크로모니터).

## 2. 전체 구조

```text
personal-investment-platform/
├── apps/
│   ├── web/         # Next.js 15 대시보드
│   ├── api/         # FastAPI + SQLAlchemy + Alembic
│   ├── worker/      # PostgreSQL polling worker
│   └── collector/   # 레거시 엔진 재사용 계산 서비스 (S: 마운트 · profile 게이트)
├── database/
│   ├── migrations/  # Alembic 마이그레이션
│   └── seeds/
├── workflows/n8n/   # n8n 워크플로 JSON + 운영 메모(README)
├── storage/
│   ├── raw/         # 업로드된 원본 CSV
│   ├── processed/   # 검증·정규화된 CSV
│   └── trigger/     # n8n ↔ 윈도우 워처 파일 드롭 다리
├── tools/           # 윈도우 사이드카 (perf-brief-runner 등)
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
| collector | 레거시 엔진 계산 서비스 | (없음 · 내부 8100) |

`collector` 는 `profiles: ["collector"]` 게이트라 기본 `make up` 으로는 안 뜬다. 최초 1회만 아래로
띄우면 그 뒤부터는 Docker 재시작 때 자동 기동된다(`restart: unless-stopped`).

```bash
docker compose --profile collector up -d collector
```

S: 공유 폴더를 여러 갈래로 마운트하는데 **입력과 엔진은 전부 `:ro`** 다. 쓰기가 열린 곳은
`output/` · `funds/` · `lp_eval/` · `.cache` 뿐이다(compose 주석 참조).

컨테이너 내부 통신은 서비스 이름으로 한다 (`http://api:8000`, `http://collector:8100`, `postgres:5432`). `localhost`는 쓰지 않는다.

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

화면은 사이드바 그룹으로 묶여 있다.

| 그룹 | 화면 |
|---|---|
| 시장 모니터링 | `/inav` iNAV 모니터 · `/wrap` WRAP · `/lp-eval` LP 평가 |
| 뉴스 모니터링 | `/telegram-news` 텔레그램 |
| Quant | `/macro` 매크로 |
| 성과 분석 | `/track-record/torus-aicoretech` TORUS/AI테크 |
| 기타 | `/ai-token-usage` · `/lan-dashboard` · `/stock-discussion` 종토방 · `/meeting` 회의 · `/settings` |
| 골격 | `/` 메인 · `/data-operations` 작업·CSV |

사이드바에 href 가 없는 항목(모멘텀·재무·sentiment·FUND3 등)은 아직 페이지가 없는 자리다.

## 9. FastAPI 문서 주소

http://localhost:8000/docs (Swagger UI)

## 10. n8n 접속 주소

http://localhost:5678

### 등록된 워크플로

| 파일 | 워크플로 | 스케줄 |
|---|---|---|
| `create-test-job.json` | Create Test Job (연동 검증용) | 수동 |
| `perf-report-daily.json` | 성과분석 보고서 생성 | 평일 08:30~10:30 10분 간격(13회) · 월요일엔 주간도 |
| `weekly-report-daily.json` | 주간가격 · 매크로 리포트 생성 (id `daily-reports`) | 주간가격 평일 08:30~10:30 13회 + 10:35 점검 / 매크로 평일 07:50 1회 |

블룸버그 BDH 워크북을 **사람이 저장해야** 새 종가가 들어오는데 그 시각이 07:5x~09:4x 로 흔들려서,
한 번이 아니라 도착할 때까지 두드리는 구조다. 중복 생성은 서버·윈도우 쪽 게이트가 막는다.
설계 근거와 함정은 `workflows/n8n/README.md` 에 정리돼 있다.

### n8n 워크플로 import

- **UI**: http://localhost:5678 접속 → 우측 상단 메뉴 → **Import from File** → JSON 선택.
- **CLI** (`./workflows/n8n`가 컨테이너의 `/workflows`로 마운트되어 있다):

  ```bash
  docker compose exec n8n n8n import:workflow --input=/workflows/create-test-job.json
  docker compose exec n8n n8n list:workflow          # 무엇이 등록·활성인지 확인
  ```

`import:workflow` 는 워크플로를 **비활성 상태로** 넣는다(이미 활성이던 것도 재import 하면 꺼진다).
스케줄이 실제로 돌게 하려면 `publish:workflow --id=...` 후 `docker compose restart n8n` 이 필요하다.

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
