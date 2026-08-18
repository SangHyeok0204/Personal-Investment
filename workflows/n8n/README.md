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

## 성과분석 보고서 일간 생성 (`perf-report-daily.json`)

운용역이 `비교PORT_분석.bat` · `전기차PORT_분석.bat` 을 손으로 돌리던 자리를 대신한다. 산출물은 대시보드 `/track-record/torus-aicoretech` 에 그대로 뜬다 (`/perf-report` 가 `output/{생성일}/` 을 훑는 기존 배선).

- **트리거**: Schedule 2개 (Asia/Seoul).
  - `평일 08:30~10:30 · 10분` → `scope=일간`. **08:30 · 08:40 · 08:50 / 09:00~09:50 10분 간격 / 10:00 · 10:10 · 10:20 · 10:30** = 하루 13회.
  - `월요일 08:30~10:30 · 10분` → `scope=주간`. 같은 시각표에 요일만 월요일(`* * 1`). 월요일엔 두 트리거가 각각 돌아 일간·주간이 다 나온다.
  - 게이트가 `scope` 별로 따로 잡히므로(`_prev_as_of(who, scope)`) 둘이 서로를 막지 않는다.
  - `cronExpression` 은 **6필드이고 첫 자리가 초**다. `*/10 30-59 8 * * 1-5` 로 쓰면 10분이 아니라 **10초마다** 돌아 30분간 180번 발화한다. 반드시 `0 30,40,50 8 * * 1-5` 형태로 초를 0 에 고정할 것.
- **호출 API**: `POST http://collector:8100/perf-report/generate?scope=일간`
  - `scope` 는 `일간` · `주간` · `월간`. `force=true` 는 게이트를 무시하고 무조건 만든다 (수동 재생성용, 스케줄은 안 쓴다).
  - 타임아웃 600초. SMB + openpyxl 이라 두 보고서에 수십 초가 걸린다.
- **왜 13번이나 부르는가**: 소스가 블룸버그 BDH 워크북이라 **사람이 엑셀에서 열어 저장해야** 새 종가가 들어온다. 실제 저장 시각이 07:5x ~ 09:4x 로 흔들려서 한 번만 부르면 전날 숫자로 보고서가 나간다. 도착할 때까지 두드리는 구조다.
- **중복은 서버가 막는다**: `perf_generate` 가 `Price 시트 마지막 영업일 > 이미 만든 보고서의 기준일` 일 때만 만든다. 이미 있으면 `status: skip` 으로 즉시 돌아온다. 그래서 13번을 불러도 기준일당 한 번만 생성된다. 휴장일엔 시트가 안 늘어나 저절로 건너뛴다 — 휴장일 캘린더가 필요 없다.
- **출력**: `{ ran, sourceStale, results: [{target, status, asOf, file, reason}], fundSeries }`
  - `status` 는 `ok`(생성) · `skip`(이미 최신 또는 소스 미갱신) · `error`.
  - `ran` 이 참이면 누적수익률 시계열(`funds/*.json`)도 같이 갱신한다.
- **알림 분기**: IF 노드가 `sourceStale == true` 이고 시각이 10시를 넘었으면 "미갱신 알림" 으로 보낸다. 지금 그 자리는 **NoOp 자리표시자**다 — 실제 채널(슬랙·메일 등)로 바꿔 끼울 것.
- **실패 처리**: HTTP 노드가 4xx/5xx 를 받으면 실행이 실패로 남는다(**Executions** 화면에서 빨갛게 보인다). 일부러 `neverError` 를 끄고 두었다. 10분 뒤 다음 발화가 다시 시도한다.

> **엔진은 S: 가 정본이다.** collector 는 `/srv/legacy/perf_analysis/분석엔진` 을 `sys.path` 에 얹어 그대로 임포트한다. 다만 **파이썬 모듈 캐시 때문에 프로세스당 한 번만** 읽는다 — S: 의 엔진을 고쳤으면 `docker compose --profile collector restart collector` 를 해야 반영된다.

> **쓰기 범위**: 마운트는 `:ro` 가 원칙이고 `output/` 과 `funds/` 두 하위 폴더만 `:rw` 로 겹쳐 걸었다(compose 참조). 입력 엑셀과 엔진 코드는 컨테이너가 못 건드린다.

## 주간가격 · 매크로 리포트 일간 생성 (`weekly-report-daily.json`)

운용역이 손으로 돌리던 두 자리를 대신한다 — 주간가격모니터 `make_report.bat`, 매크로모니터 `일간HTML생성.bat`.
다리(파일 드롭)와 윈도우 워처를 공유하므로 워크플로 하나에 두 갈래로 넣었다 (매크로는 2026-08-12 추가).

> **파일명과 워크플로 id 가 어긋난다.** 파일은 `weekly-report-daily.json` 인데 안의 `id` 는 **`daily-reports`**,
> 이름은 "주간가격 · 매크로 리포트 일간 생성" 이다 (주간가격만 있던 시절 이름이 파일에 남았다).
> `publish:workflow --id=` 에는 파일명이 아니라 `daily-reports` 를 준다.

### 다리 — 파일 드롭

n8n 은 WSL 안 리눅스 컨테이너라 윈도우 프로세스를 못 띄운다. SSH 를 놓으려다 대상 PC 의 샌드박스 ACL
(`CodexSandboxUsers` 가 프로필에 쓰기 가능 → OpenSSH StrictModes 가 키를 거부)에 막혀 파일 드롭으로
선회했다(2026-08-11). 관리자 권한이 필요 없다.

```
n8n  →  /files/trigger/{job}.request.json   (컨테이너)
        = \\wsl.localhost\Ubuntu\home\user\projects\personal-investment-platform\storage\trigger\   (윈도우)
n8n  ←  /files/trigger/{job}.result.json    ← 윈도우 워처가 기록
```

**트리거 폴더는 S: 가 아니라 WSL ext4 다**(2026-08-12 이전). 처음엔 `S:\GE\raw\data\주간가격모니터\_trigger`
였는데 n8n 이 `The file "..." is not writable` 로 거부했다. SMB/9p 탓이라 짐작하고 옮겼지만 **그 짐작은
틀렸다** — ext4 에서도 같은 오류가 났다. 진짜 원인은 `N8N_RESTRICT_FILE_ACCESS_TO` 의 기본값이 빈 값이
아니라 `~/.n8n-files` 인 것이었고, compose 에서 `/files` 로 지정해 풀었다. 지금 자리를 유지하는 건 이 폴더가
이미 `.\storage:/files` 로 물려 있어 허용 경로와 그대로 맞아떨어지기 때문이다.
**S: 의 `_trigger` 폴더는 이전 전 잔재다** — 거기 결과 파일을 보고 판단하지 말 것(2026-08-12 08:35 에서 멈춰 있다).

**윈도우 쪽에 상주 워처가 하나 필요하다**: `주간가격모니터\run_trigger_watch.bat` 을 **claude CLI 가 있는 PC**
에서 창 하나 켜 둔다(2026-08-12 재기동 기준 호스트명 `글로벌주식파트3H`, 생존 포트 59323). 20초마다 트리거
폴더를 본다. 수집 워처(`run_watch.bat`, .199.120)와는 별개이고 같은 기계일 필요도 없다 — 둘 다 S: 를 공유한다.
살아 있는지는 `S:\GE\raw\data\주간가격모니터\cache\trigger_log.txt` 꼬리로 확인한다.

**등록된 작업만 돈다**: `pipeline/trigger_watch.py` 의 `JOBS`(`weekly-report` · `macro-daily`)에 없는 job
이름은 거부한다. 트리거 폴더에 아무 파일이나 떨어뜨려 임의 명령을 돌리는 길을 막는다. 요청 파일은 **읽자마자
0바이트로 비워** 선점하고(수 분 걸리는 작업이 겹쳐 돌지 않게), 결과 파일은 임시 이름으로 쓴 뒤 rename 한다
(SMB 에서 쓰다 만 JSON 이 그대로 보이기 때문).

### 갈래 ① 주간가격모니터 (`weekly-report`)

- **트리거 2개**
  - `평일 08:30~10:30 · 10분` → 요청 파일을 떨어뜨리기만 하고 끝난다(하루 13회). 결과를 기다리지 않는다.
  - `평일 10:35 · 결과 점검` → 결과 파일을 읽어 알림 여부만 판정한다. Wait 노드를 안 써서 경쟁 조건이 없다.
- **실행**: `python -m pipeline.report_from_processed --if-fresh --json --date {오늘}` (cwd = 주간가격모니터 프로젝트 루트)
- **산출물**: `S:\GE\raw\data\주간가격모니터\output\results\{기준일}\`
- **왜 13번이나 부르는가**: 소스가 블룸버그 BDH 워크북이라 **사람이 엑셀에서 열어 저장해야** 새 종가가
  들어오고, 그 시각이 07:5x~09:4x 로 흔들린다. 도착할 때까지 두드리는 구조다.
- **중복은 윈도우가 막는다**: `pipeline/gate.py` 가 `시트 최신 행 >= 기준일` 이고 `기준일 산출물이 아직 없을`
  때만 만든다. 이미 있으면 `status: skip`. 그래서 13번 불러도 기준일당 한 번만 생성된다.
  휴장일엔 사람이 엑셀을 저장하지 않아 시트가 안 늘어나므로 저절로 건너뛴다 — **휴장일 캘린더가 필요 없다**.
- **알림 분기**: 10:35 판정이 셋 중 하나면 알림이다 — ① 오늘 실행 기록 없음(`finishedAt` 이 오늘이 아니다
  = 워처가 꺼졌다) ② `status=error` ③ `stale=true`(엑셀이 아직 안 들어옴).

### 갈래 ② 매크로모니터 (`macro-daily`)

- **트리거**: `평일 07:50` **1회**. 게이트가 없다 — 소스가 investing.com 크롤이라 '갱신을 기다릴' 신호 자체가
  없어서, 사용자 지정 시각에 무조건 돈다.
- **실행**: `python -X utf8 main.py {오늘}` (cwd = `S:\GE\raw\모니터링\실시간 모니터링\매크로모니터`).
  날짜는 **위치 인자**다 — 안 주면 "오늘 일자로 생성하시겠습니까? [Y/n]" 프롬프트가 stdin 없이 EOFError 로
  빠지는 우연에 기대게 된다.
- **산출물**: `S:\GE\raw\data\매크로모니터\output\results\매크로캘린더_{YYMMDD}_{1,2}.html` (2장)
- **성패 판정은 종료 코드뿐이다**: `main.py` 가 결과 JSON 을 안 뱉어서 `JOBS` 에 `json: False` 로 걸려 있다.
  exit 0 이면 `status: ok`, 아니면 `error`.
- ⚠️ **결과를 아무도 안 읽는다**: 10:35 점검 노드는 `weekly-report.result.json` **하나만** 읽는다.
  매크로가 `status: error` 로 끝나도 조용히 지나간다. 매크로용 점검 갈래를 붙이거나 점검 노드를 두 파일 다
  읽도록 고칠 것.

### 공통

- `cronExpression` 은 **6필드이고 첫 자리가 초**다. `*/10 30-59 8 * * 1-5` 로 쓰면 10분이 아니라
  **10초마다** 돌아 30분간 180번 발화한다. 반드시 `0 30,40,50 8 * * 1-5` 형태로 초를 0 에 고정할 것.
- **알림은 아직 안 나간다**: 판정까지만 하고 그 끝은 **NoOp 자리표시자**다. 실제 채널(슬랙·메일 등)로
  바꿔 끼울 것. 주간가격 쪽 알림 3종도 마찬가지로 지금은 아무 데도 안 간다.
- **결과 계약** (`{job}.result.json`)
  ```json
  { "job":"weekly-report", "startedAt":"...", "finishedAt":"...", "exitCode":0,
    "result": { "ran":false, "status":"skip", "stale":true, "asOf":"2026-08-11", "reason":"...", "file":"..." } }
  ```
  `result.status` 는 `ok`(생성) · `skip`(미갱신 또는 이미 최신) · `error`.
- **수동 버튼은 그대로 남아 있다**: n8n 이 꺼져도 사람이 눌러 만들 수 있다 —
  주간가격 `make_report.bat`(게이트 없음) · `run_auto.bat`(게이트 있음), 매크로 `일간HTML생성.bat`.

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

### 3) 활성화 (스케줄 워크플로만 해당)

`import:workflow` 는 워크플로를 **비활성 상태로** 넣는다(이미 활성이던 것도 재import 하면 꺼진다). 스케줄이 실제로 돌게 하려면 publish 후 n8n 을 다시 띄워야 한다.

```bash
docker compose exec n8n n8n import:workflow --input=/workflows/perf-report-daily.json
docker compose exec n8n n8n publish:workflow --id=perf-report-daily

docker compose exec n8n n8n import:workflow --input=/workflows/weekly-report-daily.json
docker compose exec n8n n8n publish:workflow --id=daily-reports   # ★ 파일명이 아니라 id

docker compose restart n8n          # 재시작해야 트리거가 등록된다
```

지금 무엇이 켜져 있는지는 이렇게 본다 (2026-08-13 기준 `perf-report-daily` · `daily-reports` 둘 다 활성).

```bash
docker compose exec n8n n8n list:workflow
```

`n8n execute --id=...` 로는 검증할 수 없다 — Schedule Trigger 만 있는 워크플로는 CLI 실행 대상이 아니다("Missing node to start execution"). 배선을 확인하려면 HTTP 호출을 직접 해 보면 된다.

```bash
docker compose exec n8n node -e '(async()=>{const r=await fetch("http://collector:8100/perf-report/generate?scope="+encodeURIComponent("일간"),{method:"POST"});console.log(r.status, JSON.stringify(await r.json()));})()'
```

import 후 워크플로를 열고 **Execute Workflow**를 누르면 작업이 생성된다. worker가 작업을 처리하려면 먼저 `docker compose exec api alembic upgrade head`로 마이그레이션이 끝나 있어야 하고, `.env`에 `INTERNAL_API_KEY`가 있어야 한다(compose가 n8n·api에 주입).
