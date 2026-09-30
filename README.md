# 개인 투자 플랫폼 (Personal Investment Platform)

Windows + WSL2 + Docker Desktop 환경에서 실행되는 로컬 개인 투자 플랫폼이다.
2026-07 에 작업(job) 파이프라인 골격으로 시작해, 지금은 개인 리서치·모니터링 화면을
얹은 대시보드로 쓰고 있다. 골격은 그대로다 — 백그라운드 일은 전부 작업 하나로 수렴한다.

```text
Next.js 화면에서 작업 실행
  -> FastAPI가 작업 생성
  -> PostgreSQL에 작업 상태 저장
  -> Python Worker가 작업 처리
  -> PostgreSQL 작업 상태 갱신
  -> Next.js에서 진행 결과 확인
```

여기에 한 갈래가 더 붙어 있다.

- **n8n** — 스케줄 자동화. `POST /internal/jobs` 로 작업을 만들기도 하고, 파일 드롭으로 일을
  넘기기도 한다(`storage/trigger`). 자세한 건 `workflows/n8n/README.md`.

> 2026-09-30: 사내 경로·LAN 에 묶여 있던 `collector` 서비스는 폐기했다. 남은 화면의 원천은
> 무료 공개 데이터(FRED · KRX · OpenDART 등)를 api 가 직접 읽는다 — 사내 경로·LAN 의존 0.

## 1. 목적

- 로컬에서 도는 작업 처리 파이프라인 (job 생성 → worker 처리 → 상태 조회).
- 개인 투자 리서치·모니터링을 한 화면에 모으기 (매크로 · AI Key Data · 국내 ETF · 13F 등).
- 손으로 돌리던 리포트 생성을 스케줄로 대체하기.

## 2. 전체 구조

```text
personal-investment-platform/
├── apps/
│   ├── web/         # Next.js 15 대시보드
│   ├── api/         # FastAPI + SQLAlchemy + Alembic
│   └── worker/      # PostgreSQL polling worker
├── database/
│   ├── migrations/  # Alembic 마이그레이션
│   └── seeds/
├── workflows/n8n/   # n8n 워크플로 JSON + 운영 메모(README)
├── storage/
│   ├── raw/         # 업로드된 원본 CSV
│   ├── processed/   # 검증·정규화된 CSV
│   └── trigger/     # n8n ↔ 윈도우 워처 파일 드롭 다리
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

화면은 사이드바 그룹으로 묶여 있다.

| 그룹 | 화면 |
|---|---|
| Quant | `/macro` 매크로 |
| 기타 | `/stock-discussion` 종토방 · `/settings` |
| 골격 | `/` 메인 · `/data-operations` 작업·CSV |

사이드바에 href 가 없는 항목(모멘텀·재무·sentiment·FUND3 등)은 아직 페이지가 없는 자리다.

## 9. FastAPI 문서 주소

http://localhost:8000/docs (Swagger UI)

### Docker 없이 로컬에서 직접 돌리기

개발 중에는 컨테이너 없이 네이티브 Postgres + uvicorn + next dev 로도 돌린다.

먼저 **`.env.local`** 을 만든다(저장소 뿌리, git 에 올리지 않는다).

```bash
cat > .env.local <<'EOF'
DATABASE_URL=postgresql+psycopg://<user>@localhost:5432/investment

# (선택) 리서치 자료 폴더 — 적으면 '리서치 라이브러리' 화면이 켜진다.
# ⚠️읽기 전용이다. 이름·크기·수정시각만 읽고 **내용은 열지 않으며**, 파일을
#   옮기거나 고치지 않는다. 지정한 폴더 밖으로도 나가지 않는다(링크 포함).
# RESEARCH_DIR=/Users/<me>/Documents/05_리서치
EOF
```

⚠️**`.env` 가 아니라 `.env.local` 이다.** `.env` 는 docker compose 용이라 DB
호스트가 `postgres`(컨테이너 이름)이고, 호스트 셸에서는 그 이름이 풀리지 않는다
(`nodename nor servname provided`). 코드는 `.env.local` 을 **저장소 뿌리 절대경로**
로 읽으므로 어느 디렉터리에서 실행해도 같게 동작한다 — `scripts/*.py` 는 뿌리에서,
pytest 는 `apps/api` 에서 돌기 때문에 상대경로로 두면 한쪽에서만 읽힌다.
환경변수가 이 파일보다 우선하므로 일회성 덮어쓰기는 `DATABASE_URL=... <명령>` 으로 한다.

```bash
# API — ★포트는 8000 을 쓴다
cd apps/api
../../.venv/bin/python -m uvicorn app.main:app --port 8000 --reload \
  --reload-dir . --reload-dir ../worker

# 웹 (별도 터미널)
cd apps/web && npm run dev
```

⚠️**API 포트를 8000 이외로 바꾸지 말 것.** 웹은 `NEXT_PUBLIC_API_BASE_URL` 이
없으면 `http://localhost:8000` 을 쓰고, 이 값은 **빌드 시점에 번들에 박힌다**.
포트를 바꾸면 dev 는 환경변수로 넘길 수 있어도 프로덕션 빌드는 조용히 8000 을
가리킨 채 나온다(실제로 그런 번들이 나왔다).

⚠️**`--reload-dir ../worker` 를 빼지 말 것.** API 는 시세·공시 소스를
`apps/worker/prices/` 에서 import 하는데, `--reload` 는 기본적으로 실행 디렉터리
(`apps/api`)만 감시한다. 그래서 worker 쪽을 고치면 **코드는 바뀌었는데 API 는
옛날 것을 들고 있다.** 세 번 겪고 나서야 원인을 찾았다 — 증상이 "고친 게 반영이
안 된다"라서 캐시나 빌드를 먼저 의심하게 된다.

⚠️**앱은 `investment`, 테스트는 `investment_test` 다. 절대 같은 DB 를 쓰지 말 것.**
pytest 의 `db` 픽스처는 매 테스트마다 `TRUNCATE ... CASCADE` 를 돈다. 앱을
`investment_test` 에 붙여 두면 테스트를 한 번 돌릴 때마다 대시보드 데이터가
사라진다(실제로 여러 번 겪었다). 테스트 DB 이름은 `apps/api/tests/conftest.py`
가 정한다.

```bash
# 앱 DB 를 처음 만들 때
createdb investment
DATABASE_URL="postgresql+psycopg://<user>@localhost:5432/investment" \
  .venv/bin/python -m alembic upgrade head
# 그 다음 대시보드의 [연동/설정] → 동기화, 또는
curl -X POST http://localhost:8000/api/v1/brokerage/sync
```

이력 동기화(체결·주문·배당·실현손익·일별성과)는 **영업일 16:30(KST)** 에 API 가
스스로 한 번 돌린다(국내장 마감 직후). 정각 타이머가 아니라 "가장 최근에 지나간
영업일 16:30 이후로 안 돌았으면 지금 돈다"라서, 그 시각에 맥이 자고 있었거나
uvicorn 이 꺼져 있었으면 **다음에 켤 때 따라잡는다.** 브라우저는 안 열어도 된다
(`apps/api/app/core/daily_sync.py`).

⚠️**이른 아침(KST 05~07시경)에는 동기화하지 말 것.** 키움 `usa21670`(일별 계좌
성과)이 그 시간대에 **에러 없이 빈 배열**을 돌려준다("정상적으로 처리되었습니다"
+ 0행). 같은 조회가 23시에는 530행이었다. 예외가 안 나므로 새 DB 를 그때 채우면
이력이 빈 채로 굳는다. 동기화 응답의 경고 문구가 이 경우를 알려 준다.

```bash
# 빌드 검증 — dev 서버의 .next 를 덮지 않도록 출력 폴더를 가른다
cd apps/web && npm run build:check

# 화면 간 숫자 정합성 대조 (서버가 떠 있어야 한다)
.venv/bin/python scripts/audit_consistency.py

# 시드가 증권사가 준 사실과 어긋나지 않는지 (ETF 를 새로 사면 먼저 돌릴 것)
.venv/bin/python scripts/audit_seeds.py

# 금액·단가·수량 표시 규칙 (서버가 필요 없다)
cd apps/web && npx tsx ../../scripts/check_format.ts

# 결제 지연(T+2) 재측정 — 매매일지 창이 아직 맞는지 (매매가 쌓이면 다시 돌릴 것)
.venv/bin/python scripts/measure_settlement_lag.py
```

⚠️`check_format.ts` 의 절반은 **반올림하면 안 되는 것들**이다. 금액이 소수점을
잘라 버려 칸끼리 합이 1원 안 맞던 것을 고치다가, 정수부를 올리는 로직을 공통
파서에 넣는 바람에 단가 139.90 이 "140.90" 이 될 뻔했다. 금액은 반올림하고
단가·수량은 그대로 둔다 — 그 경계를 이 파일이 지킨다.

⚠️**거래소 코드는 `broker_exchange_codes` 에 쌓인다**(alembic 0017). 배당 조회는
종목마다 거래소(ND/NY/NA)를 알아야 하는데 잔고 응답이 알려주지 않아 더듬어 찾는다.
찾은 코드를 남기지 않으면 동기화마다 한 종목에 최대 3번 헛 조회가 나간다. 판 종목은
`assets` 에 행이 없어 거기엔 못 남으므로 별도 표를 쓴다. 이 표를 비우면 다음 동기화가
다시 더듬을 뿐 데이터가 상하지는 않는다.

⚠️`audit_seeds.py` 는 **근거가 없는 항목을 '맞다'로 세지 않는다.** 증권사
종목명·SEC 법인명 둘 다 없으면 '확인 불가'다. 실제로 `TSL` 을 손으로 2배라고
적어 두었다가(증권사 이름은 1.25배) 나중에 발견했고, 그래서 검사를 스크립트로
만들었다 — 눈으로 한 번 훑는 것은 다음 종목에서 또 틀린다.

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
