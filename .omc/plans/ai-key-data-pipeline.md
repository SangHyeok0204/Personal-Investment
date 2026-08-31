# AI Key Data 자동 갱신 파이프라인 — 실행계획

> **2026-08-28 구현 완료 (미커밋).** 3레인 전부 라이브 검증됨.
> 수집기 `센티먼트\AI Key Data\agent\`(5소스 · npm 5,525행/594일 bootstrap 완료) ·
> 엔드포인트 6개 200 · collector 테스트 86 passed 1 skipped · 메인 그리드 12칸 무변경.
> **잔여**: ① `.bat` 상주 미기동(사람이 더블클릭) ② VS Code 증분은 스냅샷 2개째부터(내일) ③ collector 테스트 러너가 Makefile에 없음 ④ 안전망(결정 B)은 기본안

작성 2026-08-28 · team 3워크스트림 통합(ws1 판독 / ws2 배선 / ws3 수집기)
상세 설계 원본: scratchpad/ws{1,2,3}-*-design.md (2,019줄)

## 0. 정찰로 뒤집힌 전제 4건

| 최초 가정 | 실측 결과 |
|---|---|
| 마운트를 새로 걸어야 한다 | **이미 있다.** docker-compose.yml:197 `"/mnt/s/GE/raw/data/AI Key Data/input/raw:/srv/legacy/gpu_compute:ro"`. zip 4개가 컨테이너 안에서 이미 보인다(실측) |
| 대시보드에 일일 갱신 스케줄러가 필요하다 | **불필요.** 카드는 read-through — collector가 매 요청 :ro 파일 직독. 스케줄은 S:에 쓰는 쪽(ws3)만 |
| Epoch은 Playwright로 받아야 한다 | **평문 HTTPS GET으로 충분.** ETag 있음 / Last-Modified 없음 → 조건부 GET |
| OpenRouter는 CF 차단 | **틀렸다.** 인증 Datasets API는 열려 있고 `fetch_token_usage.py`가 이미 매일 수집 중(오늘 10:53 갱신) |

컨테이너 쓰기 시도 → `Read-only file system` 확인. 수집기가 Windows 측이어야 하는 근거가 구조적으로 성립.

## 1. 구조

```
[Windows] S:\GE\raw\운용 전략\센티먼트\AI Key Data\agent\
    run.py (상주, 콘솔 가시) ── npm / OpenRouter / VS Code / PyPI / Epoch
        |  .tmp -> os.replace (원자적) + 되읽기 검증 4항목
        v
[데이터] S:\GE\raw\data\AI Key Data\input\raw\   <- 유일한 접점
        |  :ro 마운트
        v
[Docker] collector build_xxx()  매 요청 직독(mtime+size 캐시)
        -> api/ai_key_data.py  _proxy_collector
        -> web/components/ai-key-data/*.tsx
```

코드/데이터 분리는 기존 관행 승계 — 코드는 `운용 전략\센티먼트\`, 데이터는 `data\`.

## 2. 확정 결정 (합의 완료)

1. **Epoch zip은 풀지 않는다.** collector가 zip 내부 직독. :ro라 제자리 추출 불가 + 이중 저장 무의미
2. **503은 collector 장애 전용.** 데이터 사유(zip 없음 / 스키마 변경 / 미수집)는 200 + 빈 series + `note`. 8/27 컴퓨팅 지수 오진 재발 방지
3. **수집기는 판단하지 않는다.** npm 7일 평활 · VS Code 음수 델타 clip 전부 다운스트림 몫. 원값만 저장
4. **신규 라우터 `apps/api/app/api/ai_key_data.py`** (`/api/v1/ai-key-data`). 기존 5개 엔드포인트 이전은 별건
5. **`_fetch_status.json`은 소프트 의존.** 부재 · 파싱실패 · 키누락 어느 경우도 카드는 정상 렌더
6. **`asof`를 순수계산 함수 인자로.** 미래 날짜 필터를 테스트로 고정
7. **OpenRouter는 `long`을 읽는다** (ws1↔ws2 충돌, 리드 재정). ws2는 wide(TOTAL 기제공·584KB)를, ws1은 long(스키마 불변)을 주장 — **long 채택**. 근거: (a) wide는 열이 397개고 top-50이 바뀔 때마다 **스키마 자체가 변형**되는 반면 long은 `date,model,total_tokens` 3열 고정, (b) 벤더 롤업은 열이름 prefix 파싱이 아니라 `model` 필드를 `/`로 쪼개는 정공법이 되고, (c) TOTAL은 groupby-sum 한 줄이며 ws1이 long과 일치 확인. 1.6MB 파싱 비용은 무시 가능(Epoch 20개 CSV 전체가 351ms)
8. **`utf-8-sig` 필수.** 두 토큰 CSV 모두 BOM+CRLF — 놓치면 첫 열이 `﻿date`로 조용히 깨짐

## 3. 데이터 함정 (실측 재현됨)

| 함정 | 증거 | 방어 |
|---|---|---|
| ARR 열 오선택 | `Annualized revenue (USD)` 53/65 vs `Revenue amount (normalize to annual)` 59/65. 차이 6행 = OpenAI 5 + Anthropic 1 (`Period type=Year`) — 덱 차트의 주인공 둘 | 후자 사용. 전자는 조용히 점을 지운다 |
| 미래 날짜 | `data_center_timelines` 78/486행이 2030까지. IT power 13,085 → **35,379 MW (2.70배)** | `Date <= asof` 필터 + 두 숫자 핀 테스트 |
| 전력 열 혼동 | `Current power` == timelines `IT power` 85/85, `Power (MW)`와는 18/85 | KPI와 차트 끝점을 같은 열로 |
| designer 누적 앵커 | Nvidia 2022-01 / Google 2022-10 / 나머지 2024-01 | `timelines_by_chip`에서 재누적(Epoch 대비 −0.9%) |
| 배경 탭 stale | query-core `queryObserver.ts:404-411` no-op + 전역 `refetchOnWindowFocus:false` | 신규 쿼리만 focus refetch, 헤더에 `{asof} 기준` |

## 4. 카드 후보와 데이터 성격

| 카드 | 원천 | 성격 | 밀도 |
|---|---|---|---|
| OpenRouter 토큰 사용량 | `tokens_daily_long.csv` (기존, 살아있음) | 일별 연속 | 최상 |
| npm 코딩에이전트 다운로드 | `npm_downloads_long.csv` (신규) | 일별 연속 | 최상 |
| AI Lab ARR | Epoch revenue_reports | **계단(step)** — 뉴스 이벤트 | OpenAI 18 / Anthropic 15점 |
| AI 칩 공급 | timelines_by_chip 160행 결측 0 | 분기 | 중 |
| 데이터센터 | data_centers 85 + timelines 486 | 불규칙 | 중 |

⚠️ Epoch 3종은 **일별 시계열이 아니다.** 연속선으로 그리면 없는 정밀도를 만든다 → payload에 `kind`(step/scatter)를 실어 서버가 소유.

### 토큰 사용량 카드가 1순위 (ws1 실측)

602 일별 포인트(2025-01-01~2026-08-27) vs ARR 카드 17포인트. 매일 자동 갱신(오늘 10:53) vs 주 1회 수기. 월 총량 2.2T → 323.4T, 최근 28일이 1년 전 같은 창의 **25.0배**. 엔드포인트 `/ai-token-usage` → `collector/ai_token_usage.py`.

**구조적 함정 4건 (전부 실측):**

| 함정 | 실측 | 처리 |
|---|---|---|
| **인구조사가 아님** | 602일 전부 정확히 51행 = top-50 + `other` 버킷(최근 30일의 6.2%, 최대 11.3%) | 총량은 유효. **모델별 "점유율" 표현은 금지** |
| 모델별 결측 = `null` ≠ 0 | top-50이 하루 중앙값 3종씩 교체 | 결측은 "순위 이탈"이지 "사용 중단"이 아님. `points`에 null 유지. ⚠️카드 B(칩 공급)는 반대 — 거기선 결측 분기가 진짜 0 |
| 요일 효과 | 토 85 / 일 87 vs 수 109 → **45%의 날이 전일 대비 음수** | 기본 표시 단위를 주간으로. 일별도 제공(가역) |
| 마지막 주 버킷은 항상 미완 | 93.4T → 71.4T가 하락으로 보이나 실은 4일치 | `incomplete` 플래그(카드 B 부분분기와 동일 처리) |

⚠️ **라이선스가 다르다.** Epoch 3종은 CC-BY(출처 표기하면 리포트 게재 가능). **OpenRouter 토큰 데이터는 파일에 라이선스가 동봉돼 있지 않다** — `license: null` + OpenRouter 출처 표기로 두고, 대외 리포트에 싣기 전 실제 이용약관 확인 필요. 임의로 조건을 지어내지 않음.

**제외**: `ai_models.zip` 전체(최신행 2025-07-09, 13.5개월 stale / all_models 6.8MB · 1,316기관), chillers · cooling_towers(날짜열 없음), `ai_companies.csv`(시계열이 콤마 문자열 한 칸), usage_reports(12/49), compute_spend(14행/2사)

## 5. 수집 주기

5분 틱은 시계만 확인, 슬롯에서만 발사. 밀린 슬롯 따라잡기 없음 — 매 사이클 **최근 35일 창 재요청**으로 자가치유(요청 1회, 폭주 아님).

| 소스 | 주기 | 근거 |
|---|---|---|
| npm | 매일 10:00 KST | 13패키지 직렬 10.0초(0.3초 페이싱). scoped bulk는 400이라 직렬 필수 |
| OpenRouter | 매일 10:05 | 전일치가 09:00 이후 안착 |
| VS Code | 매일 10:10 | 누적 스톡 — 매일이 바닥선 |
| PyPI | 매일 10:15 | 429 잦음, 3초 간격 |
| Epoch | **주 1회 월 10:20** | ETag 조건부 GET. ai_models 3.3MB, read-through 상대로 매일은 순수 낭비 |

npm 18개월 청킹은 `--bootstrap`으로 격리, 일상 루프에 없음.

## 6. 원자성 — 신규 발명 아님

`fetch_token_usage.py:18/64/69/79/90`이 **같은 출력 폴더에 이미 구현**. 승계할 것: `.tmp`를 동일 디렉터리에 생성 → `os.replace`. 신규는 2개뿐 — 최근창 병합, 되읽기 검증 4항목(크기>0 · 헤더 일치 · 행수 비감소(감소=하드실패) · 최신일자). S:가 `\\192.168.194.12\data`라 쓰기가 성공한 척하고 안 내려앉을 수 있음(`update_ramp_ai_index.py::verify_saved_workbook` 전례).

`.bat`도 `update_token_usage.bat` 골격 승계 — `cd /d "%~dp0"` + errorlevel 분기 + `pause`에 title / venv / `--interval`만 추가.

## 7. 결정 (A 확정 / B 기본안)

> **2026-08-28 사용자 승인: A = D2안.** "ADP·FOMC 내재확률을 하위 페이지로 옮겨도 돼."
> **B는 미응답 → 기본안(상주 콘솔만) 적용.** 선택안은 `--once`+runlock이 이미 있어 사후 부착 시 추가 공사 없음.


**A. 레이아웃.** `ai-key-data/page.tsx`는 6×2=12칸이 정확히 꽉 참, "스크롤 없이 본다"가 상시 지시.

탭으로 최대한 묶어도(사용량 3탭 / Epoch 3탭) 수요 4칸 · 여유 0칸.

★ **핵심: `-41%` 높이 손실은 A·B·C 공통 비용이다** — 셋 다 `rows-3`이기 때문. 따라서 그 숫자로는 셋을 가를 수 없고, 진짜 빠져 있던 건 **`rows-2`를 유지하는 안**이었다.

- **D2안 (추천)**: **그리드 무변경(높이 손실 0)**. **ADP · FOMC내재확률 2칸을 하위 페이지로 이주**시키고 그 자리에 AI 사용량 카드, Epoch도 하위 라우트. 내린 2장은 **삭제가 아니라 이주라 데이터 소실 0**. 선정 기준은 페이지 정체성("AI 밸류체인", page.tsx:10) 대비 적합도 — PolicyRate가 이미 금리축을 대표하므로 fomc_prob이 중복도 최고, ADP는 고용지표로 가장 멂. **rows-3 실측 자체가 불필요해진다**
- **C안**: `rows-3` + ComputeIndex `row-span-2` → 잔여 3칸에 사용량 카드, Epoch 하위 라우트. **D2에 지배됨** — −41%를 치르면서 Epoch도 클릭 뒤로 보내 두 비용을 다 치른다. 고를 이유는 "ADP·fomc_prob을 절대 못 내린다"일 때뿐
- **A안**: 전부 메인. ADP를 **버리고**(이주 아님) WTI 2→1칸. 지표 1개 소실 + 수술 3건 + −41%
- **B안 (탈락)**: ComputeIndex를 3×1로 → 패널당 플롯 **50.1px**(현재 99.0px). 못 읽는 차트

순위 **D2 > C > A > B(탈락)**.

### 픽셀 계산 (rows-3을 고를 때만 해당)

하드값: Topbar `h-16`+border = **65px**(topbar.tsx:25) · `pb-2` 8 · `gap-1.5` 6 · line-height = 1.5×font(Tailwind preflight, 임의값 `text-[13px]`은 font-size만 지정). `rate-chart-card` 크롬 59px(border 2 + header 32.5 + 범례 20.5 + wrapper 4) + SVG `PAD_T` 4 + `XAXIS_H` 14 → **순 플롯 = 행높이 − 77**. 추정은 `100vh` 하나뿐(1080p Chrome 최대화 ≈ 948, 북마크바 914, F11 1080).

**순 플롯 357.5px → 210.7px = −41%.** 뷰포트를 914/948/1080 어디로 잡아도 −40~41%로 일정.

210px에서 inflation 4계열은 **읽히긴 한다**(여백 제외 193px, y눈금 3개 간격 ~70px, 범례가 현재값을 글자로 띄워 선이 겹쳐도 수치는 보존). 다만 "읽힌다"와 "−41%가 작다"는 별개다.

**되돌림 원인**: `page.tsx:24-27`의 `min-h-screen` 가드 주석은 되돌린 **뒤에** 붙은 것으로 읽히고, 가드가 없던 3행 시점엔 실제로 스크롤됐을 가능성이 높다(git 미추적이라 양쪽 다 증명 불가). **단 결론엔 영향 없다** — 어느 해석이든 −41%는 그때 겪지 않은 **새 비용**이므로 "거부당한 걸 반복하는 위험"이 아니라 "새 비용을 도입하는 결정"으로 다뤄야 한다. D2를 고르면 이 논점 자체가 사라진다.

**B. 안전망.** 상주 콘솔은 창이 닫히면 죽고 재부팅을 못 넘김. VS Code 설치수는 **누락일 영구 복구 불가**(시점 누적, 과거 조회 API 없음).

- 기본안: 상주 콘솔만(요청 그대로)
- 선택안: + 하루 1회 기상해 `_fetch_status.json` 마지막 성공이 26시간 초과일 때만 `--once` 발화, 정상이면 즉시 종료. runlock(47656)이 이중 실행 차단
- 전례는 양쪽에 있음 — 증권사리포트봇이 별도 daily bat을 없앤 이유가 "백그라운드에 조용히 도는 걸 두기 싫다"였다면 선택안은 취지에 반함. 나중에 붙여도 `--once`+runlock이 이미 있어 추가 공사 없음

## 8. 순서

1. **선행 (승인 불필요)** — `agent\` 골격 + npm 수집. 기존 `fetch_token_usage.py` 옆에 나란히. 이 단계만으로 `npm_downloads_long.csv`가 쌓이기 시작
2. **VS Code 스냅샷 즉시 개시** — 누적 스톡이라 시작이 늦을수록 영구 손실. 카드보다 먼저
3. **판독 모듈** — `epoch_datasets.py` + `npm_downloads.py`, 순수계산 / IO 분리, `asof` 인자화
4. **배선** — `ai_key_data.py` 라우터 + 엔드포인트
5. **카드** — 레이아웃 결정(A) 후 착수
6. Epoch 주간 수집은 아무 때나

2번은 결정 A·B와 무관하게 지금 시작할 수 있고, 미루면 되돌릴 수 없는 유일한 항목.
