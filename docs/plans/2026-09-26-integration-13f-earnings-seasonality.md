# 외부 프로젝트 3종 편입 계획 — 13F 기관·내부자 / 어닝모니터 / 계절성

> 상태: **최종 v5 (2026-09-26) — 사용자 결정 6개 + 리뷰 2회 + 데이터 무결성 실측 점검(§D) 반영.** 착수 가능. · 20분 루프로 가정을 검증하며 갱신한다.
> 검증이 끝난 가정은 ✅, 아직 가정인 것은 ❓, 실측으로 뒤집힌 것은 ❌ 로 표시한다.

## 0. 공통 원칙

1. **collector(LAN) 의존을 없앤다.** 세 프로젝트 모두 원본이 사무실 `S:` 드라이브·Windows
   콘솔 루프·LAN collector 에 묶여 있다. 이 대시보드는 맥 한 대에서 돈다 — 데이터는
   **공개 원천(SEC EDGAR · Nasdaq · Yahoo)에서 직접** 받고, Postgres 에 쌓는다.
2. **개인 계좌 기준으로 범위를 좁힌다.** 원본은 회사 펀드(≈20개 펀드 · 380종목)
   기준이다. 여기서는 **내 보유 종목 + 관심종목**이 1차 대상이다.
   ⚠️회사 펀드 구성(보유펀드·펀드목록 열)은 **가져오지 않는다** — 공개 데이터가 아니다.
3. **파이프라인은 캐치업 루프 + 전용 실행기로 돈다.** cron 이 없다. "마지막 성공 이후 기한이 지났으면
   돌린다" 캐치업 루프 + `jobs` 테이블 + `/data-operations` 신선도.
   ⚠️(리뷰 지적) **지금 이 맥에서 `apps/worker/main.py` 는 돌지 않는다** — API 는 `.venv` uvicorn `--reload` 로
   네이티브 실행 중이고, `daily_sync` 는 worker 가 아니라 API 스레드에서 돈다. 도커 worker 는 맥의 `claude`
   로그인·화면 있는 크롬에 닿지 못한다. → **티켓 P0** 로 실행기를 먼저 정한다.
4. **화면은 지금 대시보드 패턴을 쓴다.** 위 칸 = 대표 숫자 하나(누르면 상세),
   본문 = 기간별 막대(누르면 그 기간 목록), 목록은 `전체 목록` 팝업. 한 화면(`PageContainer fit`).
5. **예측처럼 보이지 않게 쓴다.** 13F 는 이미 검증했다 — 신호 24조합 통과 0
   (`docs/guru-13f-flows.md`). 계절성도 임계값(T_SIG)을 여러 번 고친 이력이 있다.
   두 화면 모두 **"무슨 일이 있었나 / 과거에 어땠나"** 로 문구를 쓴다.

---

## 계획 A — 13F 기관·내부자

### 무엇을 가져오나
| 기능 | 원본 | 가져오나 |
|---|---|---|
| 거장 23명 13F 분기 변동(동시 리밸런싱·편입/방출·섹터 이동) | `guru_flows.py` | ✅ 핵심 |
| 거장 컨센서스·턴오버·집중도 | `storage.py`, 슬라이드 데이터 | ✅ |
| 내 보유 종목 × 거장 보유 여부 | (신규) | ✅ 신규 — 원본에 없는 개인 관점 |
| Form 4 내부자 거래(매수/매도/금액) | `form4_transactions` | ✅ 핵심 |
| 13D/13G 대량보유 | `ownership_events` | ✅ |
| 8-K/10-Q/6-K 파싱 | DB 에만 있음(코드 없음) | ⏸ 보류 — 공시 화면이 이미 목록을 준다 |
| Phase2 시그널 패널(IC 검증) | `phase2/` | ❌ 안 가져옴 — 결론(통과 0)만 화면 문구로 |
| ETF(TIGER 구글밸류체인) 기준 슬라이드 | 회사 발표용 | ❌ |

### 어디에 보이나 — 메뉴 `리서치` 아래 새 서브메뉴 2개
- **`리서치 > 거장 13F`** `/research/guru`
  - 위 칸: `이번 분기 제출 23명 중 n명`(정족수 50% 미만이면 "집계 대기") ·
    `여럿이 새로 산 종목 n` · `여럿이 전량 판 종목 n` · `내 보유 중 거장이 든 종목 n/15`
  - 본문 왼쪽: **분기별 섹터 순유입 막대**(누적, 섹터 색) → 누르면 그 분기 종목 변동표
  - 본문 오른쪽: **내 보유 종목 × 거장** 표(보유 거장 수 · 합산 비중 · 분기 증감) → 행 누르면
    그 종목을 든 거장 목록과 비중 추이
  - 칸마다 "예측 도구가 아니다" 한 줄(`docs/guru-13f-flows.md` 결론)
- **`리서치 > 내부자 거래`** `/research/insiders`
  - ⚠️**순매수 = 비파생(`is_derivative=0`) · 코드 P/S · 계획매매 아님(`is_planned_trade=0`)만 센다.**
    - A(보상 부여)·M(옵션 행사)·F(세금 원천징수)·G(증여)는 경영진의 판단이 아니다(실측: MSFT 최근 Form 4 가 A).
    - (리뷰 지적·실측 확인) 장내 매도 S 21,670건 중 **15,879건(73%)이 10b5-1 계획매도**다 — 몇 달 전에 정해 둔
      자동 매도라 "지금 팔았다"는 판단이 아니다. 섞으면 매도가 3배 이상 부풀려진다.
    - 제외한 것들은 팝업에서 회색으로 따로(계획매도는 "계획" 배지).
    - 원본 `form4_parser` 는 **첫 보고자만** 읽는다 → 공동 보고자 전부 읽도록 고친다("여러 임원 동시 매수"가 과소 집계됨).
    - Form 4/A(정정)는 새 접수번호라 **이중 집계**된다 → 정정이 원 공시의 거래를 대체하도록.
  - 위 칸: `최근 90일 내부자 순매수(달러)` · `매수 건수(드묾 — 원본 48k 중 1k)` ·
    `여러 임원 동시 매수 종목` · `최근 13D(행동주의)`
  - 본문: **월별 내부자 순매수 막대**(종목별 누적) → 누르면 그 달 거래 목록(임원명·직위·주수·가격)
  - 대상: 내 보유 + 관심종목
- 기존 `공시` 화면의 "내부자 서식 n건" 칸 → `내부자 거래` 화면으로 링크.

### 데이터·파이프라인
| 원천 | 주기 | 근거 |
|---|---|---|
| (공통) | UA 는 기존 **`SEC_USER_AGENT`**(이 저장소는 일부러 개인 이메일을 보내지 않는다 — `filings.py` 머리 주석). 새 작업은 이 값이 없으면 돌지 않고 `/data-operations` 에 "SEC UA 미설정". **프로세스 공용 속도 제한기 1개**(초당 ≤ 8) | 기본값 `…@personal-investment.local` 은 `www.sec.gov/Archives` 에서 403 위험 |
| SEC `submissions/CIK.json` (거장 23명) | **13F 시즌(분기말+30~50일) 매일 1회**, 그 외 주 1회 | 13F 는 분기 45일 마감 |
| SEC Form 4 (보유+관심종목 CIK) | **미국 영업일 1시간마다** | 원본 120초는 팀 모니터링용 — 개인에겐 과함 |
| SEC 13D/13G | 하루 2회 | |
| CUSIP→티커 | 기존 `cusip_ref` → **OpenFIGI**(무키 25요청/분·요청당 10건) → SEC 이름 매칭 | ✅실측: 기존 매핑 금액 68.1% → OpenFIGI 가 미매핑 금액 상위 100개 중 **92개** 해소(+27.6%p) → **약 96%**. 미매핑에 BAC·무디스·GE·옥시덴탈 같은 대형주가 있었다(원본 이름 정확일치 방식의 한계). 결과는 `cusip_map` 에 캐시 — 분기에 한 번만 새 CUSIP 조회 |

- 요청 규칙: UA 는 `SEC_USER_AGENT`(위 표), 403/429 지수 백오프. `prices/filings.py` 의 SEC 클라이언트를
  확장한다(새로 만들지 않는다). 기존 4스레드 병렬 호출에 **속도 제한기를 새로 건다** — 지금은 없다.
- 저장: Alembic `0022_sec_filings`(번호는 P1 규칙) — `sec_filings`(공통 색인), `holdings_13f`, `form4_transactions`,
  `ownership_events`, `cusip_map`, `guru_roster`. 스키마는 원본 `filings.db` 를 그대로 옮긴다.
- **1회성 백필**: `filings.db`(317MB, 13F 보유행 180만) → Postgres. ✅**거장 23명 · 전 기간(2013~)만**
  = **143,873행**(전체의 8%). 나머지 92%는 이름 없는 퀀트·인덱스 12곳(Citadel 19.9만·AQR 12.4만·
  Millennium·Vanguard·Two Sigma·Renaissance…)이라 "거장이 뭘 샀나"에 쓸모가 없다 — 가져오지 않는다.
  Form 4·13D/G·cusip_ref 는 전량(합계 6만 행 남짓).
- 원본 raw XML(13F 799MB · 6-K 383MB)은 **가져오지 않는다** — 재파싱용 보관본일 뿐.
- ✅**(사용자 결정 2026-09-26) 거장 23명으로 시작하되, 거장 추가가 쉬운 구조로.**
  - 거장 명단은 코드가 아니라 **DB 테이블 `guru_roster`**(cik · 표시이름 · 운용사 · `kind`(`guru`/`index`) · 추가일 · 활성여부 ·
    backfill_status)에 둔다. 원본 `watchlist.json` 의 `guru` 필드가 있는 23행을 시드로 넣는다.
  - 추가 경로: `설정 > 거장 관리`(또는 거장 13F 화면의 `+ 거장 추가`)에서 **이름으로 검색 → SEC
    `cgi-bin/browse-edgar?type=13F-HR` 에서 CIK 확인 → 추가**. 추가하면 `backfill_status='pending'` 이 되고,
    다음 수집 루프가 그 CIK 의 13F 이력을 SEC 에서 받아 채운 뒤 `done` 으로 바꾼다.
    **2013Q2 부터만**(그 전 13F 는 XML 이 아닌 텍스트 서식이라 파서가 못 읽는다).
    (원본 DB 백필이 아니라 SEC 직접 백필 — 새 거장은 원본 DB 에 없을 수 있다.)
  - 분석 함수(동시 리밸런싱·편입/방출·섹터 이동·정족수 50%)는 거장 수를 **명단에서 세도록** 한다 —
    "23" 을 코드에 적지 않는다. 비활성화하면 과거 데이터는 남기고 분석에서만 뺀다.
  - 퀀트·인덱스 12곳도 같은 테이블에 `kind='index'` 로 넣어 두되 **백필하지 않는다**(필요하면 켠다).
- 분석 로직: `apps/collector/collector/guru_queries.py`·`guru_flows.py`(단위 보정)를 API 코어로 옮기고
  collector 프록시(`inav.py` 의 `/guru-13f/*`)는 걷어낸다.
- ❌**(리뷰 지적·실측 확인) 원본의 정정공시 처리(`_LATEST_13F_CTE`)는 버그다 — 그대로 옮기면 안 된다.**
  (기관, 분기)마다 **가장 늦은 공시 하나만** 남기는데, 13F-HR/A 에는 두 종류가 있다:
  `RESTATEMENT`(전체를 다시 냄 → 앞의 것을 대체)와 `NEW HOLDINGS`(비밀유지로 늦게 공개한 **추가분** → 앞의 것에 **더함**).
  실측: 버크셔 2023-09-30 = 원본 152종목(11/14) + 재제출 152(11/16) + 추가분 **1종목(2024-05-15)** →
  "최신 하나"를 고르면 **포트폴리오가 1종목, 비중 100%** 가 된다. 이런 (기관, 분기) 묶음이 **74개**.
  → `primary_doc.xml` 의 `amendmentType` 을 읽어 RESTATEMENT 는 대체, NEW HOLDINGS 는 합산.
  raw XML 은 안 가져오므로 **74개 묶음의 표지(cover page)만 SEC 에서 다시 받는다.**
  pytest: 버크셔 2023Q3 = 152 + 1 종목.
- 13F 비중에서 **PRN(채권) 행과 put/call(옵션) 행은 뺀다**(주식 비중이 아니다). 옵션은 팝업에 따로.

#### 이식 범위 (원본 `Ongoings/구루/13F기관내부자/src`, 4,273줄)
| 원본 | 줄 | 처리 |
|---|---|---|
| `edgar/client.py` | 151 | 🔁 기존 `apps/worker/prices/filings.py` SEC 클라이언트에 **합친다**(UA·0.15s 지연·백오프 규칙만 가져옴) |
| `parsers/form4_parser.py`·`thirteen_f_parser.py`·`thirteen_dg_parser.py` | 178+145+84 | ✅ 그대로 이식 → `apps/worker/sec/parsers/` |
| `collectors/form4.py`·`thirteen_f.py`·`thirteen_dg.py`·`base.py` | 117+80+95+93 | ✅ 이식 → worker 작업 핸들러(`SEC_FORM4`, `SEC_13F`, `SEC_13DG`) |
| `resolver.py`·`normalize.py` | 177+122 | ✅ 이식 + **OpenFIGI 단계 추가** |
| `storage.py` | 954 | 🔁 SQLite → SQLAlchemy/Postgres. 조회 함수는 이미 벤더 사본(`guru_queries.py` 668줄)이 있다 — 그걸 기준으로 |
| `flows.py` | 561 | ✅ = 벤더 사본 `guru_flows.py`. 이식 후 collector 쪽 사본 삭제 |
| `gurus.py`·`registry.py`·`subscriptions.py` | 46+134+127 | 🔁 `watchlist.json` 단일파일 → **`guru_roster` 테이블 + 기존 `watchlist_items`** |
| `pollers.py` | 130 | 🔁 asyncio 폴러 → `daily_sync` 식 캐치업 루프(주기표대로) |
| `server.py`·`events.py`·`static/` | 258+54 | ❌ 자체 FastAPI·SSE·단일 HTML — 대시보드가 대신 |
| `report_html.py`·`treemap.py` | 293+291 | ❌ 배치 HTML. 트리맵 **계산식**(면적=Σ\|Δ비중\|, 색=순bp)만 화면 설계에 참고 |
| `prices.py` | 105 | ❌ FactSet parquet 의존 — 필요하면 기존 Yahoo 시세로 |
| `config.py`·`central_paths` | 78 | 🔁 `core/config.py` 설정으로 |
**이식 약 2,300줄 / 버림 약 1,000줄 / 대체 약 1,000줄.**

### 위험·미정
- ✅원본 코드 확인: `OneDrive-개인/Ongoings/구루/13F기관내부자/src` — `parsers/form4_parser.py`,
  `edgar/`(클라이언트), `resolver.py`, `flows.py`, `storage.py`, `pollers.py`. **→ 계획 A 는 재구현이 아니라 이식이다.**
  8-K/10-Q/6-K 파서는 여기에도 없다(DB 가 코드보다 앞서 있음) — 보류 결정과 맞다.
- 데이터 품질: 미래 날짜 Form 4(GOOGL 2027-01-25), 보유행 없는 13F 4건, 버크셔 이름 2종 — 적재 시 검사.

---

## 계획 B — 어닝모니터

### 무엇을 가져오나
| 기능 | 원본 원천 | 여기서 |
|---|---|---|
| 실적 발표 캘린더(일자·장전/장후·컨센) | Investing.com Playwright 크롤 | **Nasdaq API**(이미 `/stock/us` 가 씀) — 크롤러 제거 |
| 실적 vs 컨센(EPS 서프라이즈) | Investing.com + 8-K | ✅Nasdaq `calendar/earnings`(eps·epsForecast·surprise·noOfEsts)·`quote/{sym}/eps`·`analyst/{sym}/estimate-momentum` |
| 매출 컨센 | Investing.com | ✅**(사용자 결정) 2안 — Investing.com 캘린더 1일 1회 크롤(Playwright)**. ⚠️(리뷰) 원본 크롤러는 **화면에 보이는 크롬**(`channel="chrome", headless=False`)을 띄운다 — 2026-07-17 부터 Cloudflare 가 헤드리스를 막아서. → 맥 **로그인된 화면 세션**에서만 돈다(도커 불가, 화면 잠금 시 실패 가능 ❓실측 필요). Playwright 는 지금 `.venv` 에 없다 — 설치 필요. Nasdaq·Yahoo 는 무료로 매출 컨센을 주지 않는다(실측). 크롤이 막히면 그날은 매출 컨센 칸을 "수집 실패"로 두고 EPS(Nasdaq)는 그대로 보인다 |
| 가이던스 | 8-K 파싱 → SQLite `guidance` | SEC 8-K (A 의 SEC 클라이언트 공유) |
| 관전포인트 4개 → 결과 (LLM) | 로컬 `claude -p`/`codex` CLI | ✅**(사용자 결정) 이 맥의 `claude` CLI**(`claude -p`, 서브프로세스) |
| 발표 후 주가 반응 | 토스 1분봉 | **토스**(이미 `quote_cache` 가 씀). ✅실측: `candles?interval=1m&before=` 로 **30일 전 장후(ET 17:30 까지)** 1분봉도 받아진다 → 맥이 잠들어 제때 못 돌아도 **나중에 캐치업으로 다시 계산 가능** |
| 주간 회의 슬라이드 · Slack 웹훅 | | ❌ 팀 회의용 — 가져오지 않음 |
| 종목 이슈 알림(레딧 언급 급증) | ChartExchange 스크랩 | ⏸ 3단계 — 보유 종목 필터로 축소 |

✅**원본 소스 확보(2026-09-26)**: 사용자가 `OneDrive-개인/Ongoings/src/` 로 옮겨 둠 — `.py` 33개, 16,683줄.
**→ 재구현이 아니라 이식.** ⚠️**이식이 끝나면 `Ongoings/src/` 는 삭제한다(사용자 지시)** — 마지막 단계에 둔다.

| 원본 파일 | 줄 | 처리 |
|---|---|---|
| `earnings_crawler.py` | 565 | ✅ 이식 — Investing.com 크롤(매출 컨센, 2안) |
| `sec_edgar.py`·`exhibit_parser.py`·`segment_10q.py`·`segment_store.py`·`segment_desc.py` | 681+231+388+758+… | ✅ 이식 — 8-K Ex.99.1·가이던스·세그먼트. SEC 클라이언트는 A 와 공유로 합친다 |
| `earnings_store.py` | 1,548 | ✅ 이식 — SQLite → Postgres(`0024_earnings`(번호는 P1 규칙 — 0023 은 A5 `cusip_sector` 가 먼저 가져갔다)) 로 저장 계층만 교체 |
| `watching_points.py` + `prompts/watching_points_expert.md` | 989 | ✅ 이식 — 관전포인트 |
| `market_reaction.py` + `prompts/market_reaction_expert.md`·`toss_prices.py`·`stock_returns.py` | 970+285+470 | ✅ 이식 — 발표 후 반응(토스는 기존 `prices/toss` 와 합친다) |
| `llm_cli.py` | — | ✅ **`codex exec` → `claude -p` 로 되돌림**(원래 claude 드롭인으로 만든 파일이라 이 파일 하나만 바꾼다) |
| `run_pipeline.py` | 2,235 | ⚠️ 분해 — 슬롯 루프(`daily-server`)는 버리고 단계 함수만 worker 작업으로 |
| `alpha_vantage_client.py`·`company_overview.py` | 271+… | ⏸ 보류 — Nasdaq·Yahoo 와 겹침, 키 필요 |
| `update_holdings.py`·`import_existing_results.py` | 285+… | ❌ 회사 펀드 보유(`S:` 의 M2205 등) — 가져오지 않음. 1회 이관 스크립트만 참고 |
| `format_*.py`·`daily_slack_summary.py`·`daily_summaries.py`·`export_earnings.py`·`post_process*.py` | 약 4,500 | ❌ 엑셀·HTML 슬라이드·Slack — 화면이 대신한다 |
| `central_paths.py`·`_patch_openpyxl.py`·`business_days.py` | — | 🔁 설정(`core/config.py`)·기존 영업일 유틸로 대체 |
| `analysis_utils.py`·`web_fallback.py`·`peer_signal.py`·`report_reaction_display.py` | 954 | ✅ (리뷰 지적 — 표에서 빠져 있었음) 이식 대상 모듈이 import 한다. `web_fallback.py` 는 LLM 래퍼로 합친다 |
- 이관 원천 경로(B1): `보유종목정리.xlsx`는 `~/Downloads/어닝모니터-20260926T000926Z-1-001.zip` 안에 있다. **이 압축본에는 `EARNINGS_MONITOR.db`와 Python 원본이 없다.** 원본 DB의 전체 이관 여부는 검증할 수 없다.
  B7용 소스 백업은 아래 Codex 실행 인계 기록의 `src.zip` 및 SHA-256 manifest를 사용한다. 기능 대조가 끝날 때까지 `Ongoings/src/`를 보존한다.
- 하드코딩 비밀: 이 `src` 에는 Slack 웹훅 평문 **없음**(검사함). 평문 웹훅은 별도 모듈 `stock_issue_alert/main.py` 쪽 문서 기록이다 — 그 모듈은 3단계 보류.

### 어디에 보이나 — 기존 `리서치 > 미국 어닝/이슈` 를 확장
- 이름을 **`실적 모니터`** 로 바꾸고 `/stock/us` 를 대체.
- 위 칸: `이번 주 발표 내 종목 n` · `지난주 컨센 상회 n / 하회 n` · `다음 발표 TICKER D-n` ·
  `발표 후 최대 반응 TICKER ±x%`
- 본문 왼쪽: **주간 발표 캘린더 막대**(요일별 발표 종목 수, 장전/장후 색) → 누르면 그날 종목 카드
- 본문 오른쪽: **최근 발표 서프라이즈 막대**(EPS 서프라이즈 %, 부호) → 누르면 종목 상세
- 종목 상세 팝업: 관전포인트 ① ~ ④ → 결과, EPS/매출 실적 vs 컨센, 가이던스 변화,
  발표 후 반응(장후 16:00→17:30 ET), 8-K 원문 링크.

### 데이터·파이프라인
| 작업 | 시각 | 비고 (⚠️리뷰: 미국 시각은 `zoneinfo("America/New_York")` 로 잡는다 — KST 고정이면 11월 서머타임 해제 때 1시간 어긋남) |
|---|---|---|
| 캘린더 갱신(향후 4주) | 매일 07:10 **KST** | Nasdaq, 캐시 6h 기존대로 |
| 장후 발표 결과 수집 | **ET 17:40**(여름 KST 06:40 · 겨울 07:40) | 8-K 를 **찾거나 D+1 이 될 때까지** 15분 간격 |
| 장전 발표 결과 수집 | **ET 08:40**(여름 KST 21:40 · 겨울 22:40) | 동일 |
| 관전포인트 생성 | 발표 D-3 07:30 **KST** | LLM |
| 주간 요약 | 토 09:00 **KST** | LLM, 선택 |

- 저장: Alembic `0024_earnings`(번호는 P1 규칙 — 0023 은 A5 `cusip_sector` 가 먼저 가져갔다) — `earnings_events`, `earnings_results`, `earnings_guidance`,
  `earnings_watchpoints`.
- **1회성 이관**: 확보된 `보유종목정리.xlsx`(관전포인트 713행, 헤더 포함) 중
  **내 보유·관심종목에 해당하는 행만**. 펀드 열은 버린다.
- 보안: 원본 `stock_issue_alert/main.py` 에 웹훅 평문 하드코딩(문서 기준) — 이관 대상 아님, 사용자에게 알림.

### 위험·미정
- ✅LLM = 이 맥의 `claude -p`. 설계 조건(리뷰 반영):
  - **P0 에서 정한 네이티브 실행기**의 **LLM 전용 큐**로 부른다 — SEC·크롤 작업과 줄을 따로 세운다(한 작업이
    8분 걸려도 Form 4 수집이 밀리지 않게).
  - 호출 지점이 **두 곳**이다: `llm_cli.py` + `web_fallback.py`(직접 `claude` 호출). 둘 다 한 래퍼로 모은다.
  - 타임아웃은 원본대로 **500초**(`watching_points.py:115`) — 3분이면 대량 시간초과.
  - **격리 실행**: 임시 폴더를 작업 폴더로, 도구·MCP·훅 끔, `claude` 는 **절대경로**(서비스 PATH 에 `~/.npm-global/bin` 이 없을 수 있다).
    8-K 원문(외부 텍스트)이 프롬프트에 들어가므로 도구를 주면 프롬프트 주입 경로가 된다.
  - 쿼터: 사용자의 대화형 사용과 **같은 한도를 나눠 쓴다** → 하루 호출 상한, "사용량 초과"는 "로그아웃"과
    구분해 표시하고 **재시도하지 않는다**.
  - 불가 시 `/data-operations` 에 원인별("로그아웃" / "사용량 초과" / "시간초과")로 뜨고 관전포인트 칸은 비워 둔다.
- ✅Nasdaq 은 EPS 컨센만 준다 — 매출 컨센이 원본이 Investing.com 크롤러를 쓴 이유로 보인다.

---

## 계획 C — 계절성

### 무엇을 가져오나
| 대상 | 원본 | 여기서 |
|---|---|---|
| 지수 6개(S&P·나스닥·러셀·KOSPI·KOSDAQ·항셍) | 블룸버그 BDH 엑셀(수동 갱신) | ✅**Yahoo 월말 종가** + 블룸버그 이력 1회 시드 |
| 중국 2개(CSI300·ChiNext) | BDH | ❌Yahoo 이력 없음 · ❌Stooq 은 봇 차단(JS 챌린지). → **CSI300 은 ASHR(CSI300 추종 ETF, 2013-11~)로 이어 붙이되 "달러 ETF 대용" 표시**, **ChiNext 는 블룸버그 시드로 동결**(2026-08 에서 멈춤, 화면에 "갱신 중단" 배지) |
| S&P 섹터 11개(SOX 포함) | BDH | ✅`^SOX` + **SPDR ETF**(XLK…, 1998-12~). 섹터 지수 `^SP500-xx` 는 Yahoo 이력 없음 ❌. XLC 는 2018-06~ |
| AI/Tech 산업 33개 | 사내 분류표 + FactSet(`S:`) | ⏸ 2단계 — 이 대시보드의 분류(v3, 4,736종목)로 재구성, 무료 원천 없음 |
| 통계(평균·승률·t·FDR)·신호(상승/중립/하락)·walk-forward 백테스트 | `seasonality.py` | ✅ 로직 그대로 파이썬 코어로 |

#### 이식 범위 (원본 `Downloads/계절성`, 1,487줄)
| 원본 | 줄 | 처리 |
|---|---|---|
| `seasonality.py` 의 `tstat`·`pvalue`·`tercile_band`·`signal`·`hit`·`proof_table`·`walk_forward`·`next_month_signals`·`_selfcheck` | 약 250 | ✅ 이식 → `apps/api/app/core/seasonality.py`. `_selfcheck` 는 pytest 로 옮긴다 |
| `seasonality.py` 의 `load_prices`(BDH 엑셀 파서) | 약 25 | 🔁 1회성 시드 스크립트 `scripts/seed_seasonality_bloomberg.py` 로 |
| `sector.py` | 119 | ✅ 설정만(티커 표 → SPDR 매핑). ⚠️원본의 `sea.MIN_N = 8` 전역 변경은 **인자로** 바꾼다 |
| `industry.py` | 127 | ⏸ 2단계(산업 33개) |
| `dashboard.py`·`bars.py`·`updown.py` | 482+235+188 | ❌ HTML 생성. 화면 구성(신호 카드·월 막대·상승/하락 연도 수)만 참고 |
**이식 약 400줄.** scipy 가 없으면 p값이 정규근사로 과대평가된다 — api 의존성에 scipy 를 **고정**한다.

### 어디에 보이나 — 메뉴 `시장 모니터링 > 계절성` 신설 `/market/seasonality`
- ⚠️(리뷰 지적) 원본 `signal()` 은 **|t| 가 기준 미만이면 "상승"을 기본값으로 돌려준다**("롱 기본값") →
  "상승 5"의 대부분은 **근거 없음**이다. 화면에서 **"근거 없음(기본값)"을 따로** 센다.
  또 원본 `next_month_signals` 는 "마지막 데이터 달 + 1" = **이미 진행 중인 이번 달**이다 → 라벨을 "이번 달"로.
  적중률은 T_SIG 를 그 백테스트로 고른 **표본 내 수치**라, 칸에 두지 않고 팝업에서 "항상 상승" 기준선 옆에만.
- 위 칸: `이번 달(9월) — 근거 있는 상승 n · 하락 n · 중립 n · 근거 없음 n` ·
  `과거 평균이 유의한 달(FDR, 기준월 YYYY-MM) n개` · `내 최대 노출 섹터(반도체) 이번 달 과거 평균 ±z%` ·
  `섹터 11개 중 이번 달 과거 평균 상위/하위`
- 섹터 11개(리뷰: 화면에 자리가 없었음) → 히트맵의 **지수/섹터 전환 칩**으로 같은 격자에.
- FDR 별표는 n 이 늘면 달마다 바뀔 수 있다 → 지수·섹터를 **따로** 보정(원본과 같이), "YYYY-MM 기준" 표기.
- 본문 왼쪽: **히트맵 지수 × 12개월**(평균 수익률 색, FDR 유의 ★) → 칸 누르면
  **그 지수·그 달의 연도별 수익률 막대**(1960~) 팝업
- 본문 오른쪽: **이번 달 신호 카드**(지수별 t·n·과거 평균·승률·중립 밴드, 근거 없음은 회색) + 구간 칩(전구간/10년/5년)
- 팝업 `전체 목록`: 백테스트 표(신호별 적중률, 최근 3개월 채점).

### 데이터·파이프라인
- 월 1회: **월말 다음 영업일 07:00 KST** 캐치업 루프 → Yahoo 월말 종가 추가 → 통계·신호 재계산
  (계산은 수 초).
- 저장: `monthly_returns(series, month 'YYYY-MM', ret, source)` + `monthly_closes`(원자료 보관) +
  `seasonality_stats`, `seasonality_signals`.
- **이력 시드 + 수익률 잇기**(리뷰 반영): 블룸버그 엑셀 두 개(1960~2026-08)를 1회 적재(`source='bloomberg'`),
  2026-09 부터 Yahoo(`source='yahoo'`). ⚠️**가격 수준이 아니라 수익률로 잇는다** — 각 원천 안에서 수익률을 내고
  **정해진 달에 원천을 바꾼다.** XLK vs S5INFT, ASHR(달러·보수) vs CSI300(위안)은 수준이 원래 다르다.
  - 월 키는 `YYYY-MM` 으로 통일(Yahoo 는 월초 봉, 블룸버그는 월말 날짜).
  - **진행 중인 달은 저장하지 않는다**(월중에 캐치업이 돌아도).
  - 겹치는 과거 구간에서 두 원천의 **월 수익률 차이**를 한 번 재서 기록(수준 비교가 아니라).
- 의존성: 원본은 pandas 기반인데 `.venv`·api requirements·도커 이미지에 **pandas·numpy·scipy 가 없다** → C2 에서 셋 다 고정.
- ⚠️가격 지수(PX_LAST)와 맞추려면 Yahoo **수정전 Close** 를 쓴다(Adj Close 는 배당 포함).

### 위험·미정
- ✅Yahoo 이력 깊이 실측(아래 검증 로그). 블룸버그 시드가 **필수**다 — Yahoo 만 쓰면 S&P 가 1985 부터라
  25년, KOSPI 는 16년을 잃는다.
- ⚠️구현 함정: Yahoo `range=max&interval=1mo` 는 **간격을 제멋대로 바꾼다**(S&P 42년에 169점 = 분기 간격,
  XLC 8년에 433점). 반드시 `period1/period2` 로 요청한다. 진행 중인 달이 한 번 더 오는 중복 1행도 걷어낸다.
- 신호 임계값 T_SIG 가 1.0→0.5→0.75→0.5 로 바뀐 이력 — **과최적화 경고를 화면에 적는다.**
- 중립 적중은 설계상 1/3 상한 — 적중률 옆에 "항상 상승" 기준선을 같이 둔다.

---

## 화면 와이어프레임 (1440×900 한 화면 기준)

### A-1 `리서치 > 거장 13F`
```
┌ 26Q2 제출 18/23 ─┐┌ 여럿이 새로 산 ──┐┌ 여럿이 전량 판 ──┐┌ 내 보유 × 거장 ───┐
│ 78% · 정족수 통과 ││ 6종목  AVGO 외   ││ 4종목  UNH 외    ││ 9/15 종목에 거장  │
└─ 누르면 제출 현황 ┘└─ 누르면 목록 ────┘└─ 누르면 목록 ────┘└─ 누르면 표 ───────┘
┌ 분기별 섹터 순유입 (bp) ─────── [전체 목록] ┐┌ 내 보유 종목 × 거장 ───────────────┐
│   ▇▇                                       ││ SOXL   거장 0명 (ETF 도 13F 대상)  │
│ ▇▇██ ▇▇   ▇▇                                ││ MSFT   거장 7명 · 합산 4.1% · +0.3 │
│ ──────────────── 0 ────────────────────── ││ GOOGL  거장 9명 · 합산 6.2% · −0.8 │
│      ▆▆ ▆▆                                  ││ …  (행 누르면 거장별 비중 추이)    │
│ 24Q3 24Q4 25Q1 … 26Q2 (막대 누르면 그 분기) ││                                   │
└ ⚠️무슨 일이 있었나를 보는 화면 — 예측 아님 ┘└───────────────────────────────────┘
```
### A-2 `리서치 > 내부자 거래`
```
┌ 90일 순매수*    ┐┌ 장내 매수 건수 ─┐┌ 여러 임원 동시 매수 ┐┌ 최근 13D ─────────┐
│ −$12.4M          ││ 3건 (드묾)       ││ 1종목  NBIS        ││ 없음               │
└──────────────────┘└─────────────────┘└────────────────────┘└───────────────────┘
┌ 월별 내부자 순매수* (종목별 누적) ─────────────────────────────────── [전체 목록] ┐
│   막대 = 월, 위(빨강)=순매수 아래(파랑)=순매도 → 누르면 그 달 거래(임원·직위·주수·가격) │
│   보상 부여(A)·옵션 행사(M)·세금(F)·증여(G)·**10b5-1 계획매도(계획 배지)**는 팝업 안에 회색 │
└────────────────────────────────────────────────────────────────────────────────┘
* 순매수 = 비파생 · 코드 P/S · 계획매매 제외
```
### B `리서치 > 실적 모니터`
```
┌ 이번 주 발표 ────┐┌ 지난주 결과 ─────┐┌ 다음 발표 ───────┐┌ 발표 후 최대 반응 ─┐
│ 내 종목 3        ││ 상회 2 · 하회 1  ││ NVDA  D-4 장후   ││ CRWV −8.2% (장후)  │
└──────────────────┘└──────────────────┘└──────────────────┘└───────────────────┘
┌ 이번 주·다음 주 발표 (요일 막대, 장전/장후 색) ┐┌ 최근 발표 EPS 서프라이즈 (%) ──────┐
│ 월 화 수 목 금 │ 월 화 수 목 금               ││ ▇ MSFT +12.6   ▇ GOOGL +8.1       │
│ 막대 아래에 **내 종목 발표 목록을 바로** 보임  ││ ▆ TEM −4.0  (누르면 종목 상세)     │
│ (종목·일자·장전/장후·EPS 컨센·매출 컨센)       ││                                   │
└───────────────────────────────────────────────┘└───────────────────────────────────┘
종목 상세 팝업: 관전포인트 ①~④ → 결과 · EPS 실적/컨센 · 매출 실적/컨센(Investing.com, 수집 실패 시 표시) · 가이던스 변화 ·
발표 후 반응(장후 16:00→17:30 ET 토스 1분봉) · 8-K 원문 링크
```
### C `시장 모니터링 > 계절성`
```
┌ 이번 달(9월) 8개 ┐┌ 유의한 달(FDR) ──┐┌ 내 반도체 노출 ───┐┌ 섹터 상·하위 ─────┐
│ 근거있는 상승1   ││ 4개 ★ (26-08 기준)││ SOX 9월 평균 −1.8% ││ 상 XLU · 하 XLK   │
│ 하락1 중립2 없음4││                   ││                   ││                   │
└──────────────────┘└──────────────────┘└──────────────────┘└───────────────────┘
┌ [지수|섹터] × 월 평균수익률 [전구간|10년|5년] ┐┌ 이번 달 신호 카드 ───────────────────┐
│        1  2  3  4  5  6  7  8  9 10 11 12  ││ S&P 500   상승  t 1.4 · n 65 · 61%  │
│ S&P   ▒  ░  ▓  ▓  ░  ░  ▓  ░  █★ ░  ▓  ▓  ││ KOSPI     중립  밴드 −1.2~+1.5%     │
│ KOSPI …   (칸 누르면 그 지수·그 달 연도별 막대) ││ ChiNext   갱신 중단 배지            │
└ ⚠️T_SIG 가 여러 번 바뀐 이력 — 과최적화 주의 ┘└─────────────────────────────────────┘
```

---

## 순서 제안

| 단계 | 내용 | 이유 |
|---|---|---|
| 1 | **C 계절성**(지수·섹터) | 원천이 가장 단순(Yahoo), 코드가 온전, 1~2일 |
| 2 | **A 13F·내부자** | 기존 SEC 클라이언트·collector 로직 재사용, 백필이 크다 |
| 3 | **B 어닝모니터** | 원본 이식(16.7k줄 중 약 절반) + LLM 을 claude 로 교체 + 크롤러 · 마지막에 `Ongoings/src/` 삭제 |

## 작업 티켓 (수직 슬라이스 — 각 티켓은 끝나면 화면에서 확인 가능)

### P 공통 (먼저)
| # | 티켓 | 선행 | 완료 기준 |
|---|---|---|---|
| P0 ✅ | **실행기 결정·구성**(리뷰 Critical 1): 이 맥에서 uvicorn 옆에 **네이티브 worker** 를 `--reload` 없이 띄운다 — **LaunchAgent**(`~/Library/LaunchAgents`, `gui/$UID`; LaunchDaemon 은 로그인 세션 밖이라 `claude` 키체인·화면 크롬이 조용히 실패한다). 큐 2개(`sec_crawl` = SEC·Yahoo·**Investing.com 크롤** / `llm`), RUNNING 으로 N분 넘은 작업을 되돌리는 청소기, `/data-operations` 신선도 확장(지금은 `brokerage.py` 에만 있다) | — | 테스트 작업이 두 큐에서 동시에 돌고, 죽인 작업이 PENDING 으로 되돌아감 |
| P1 ✅ | 마이그레이션 번호 규칙: **머지 순서대로** 번호를 잡는다. ✅P0 가 **0019(`job_queues`)** 를 먼저 가져갔으므로 → **0020=계절성, 0021=월말종가 키 변경(C3), 0022=SEC, 0023=CUSIP 섹터(A5), 0024=실적**. 다른 작업이 `models.py` 를 고치는 중이라 머지 시점에 확정 | — | `down_revision` 체인 1줄 |

### C 계절성 (1단계)
| # | 티켓 | 선행 | 완료 기준 |
|---|---|---|---|
| C1 ✅ | 계절성 마이그레이션(P1 번호) + 블룸버그 엑셀 시드 스크립트 | P1 | 지수 8 · 섹터 11 적재, 월 수가 원본 `seasonality_stats.csv`·`sector_stats.csv` 의 n 과 일치 |
| C2 ✅ | `core/seasonality.py` 이식(pandas·numpy·scipy 고정, **완전 월 달력 reindex 후 수익률** — §D-0) + pytest(원본 `_selfcheck` + `seasonality_stats.csv` 수치 대조 + 항셍 빈 달) | C1 | 원본 통계와 일치 — 기준값 예: 전구간 SPX 1월 n=66 · 평균 1.19 · 상승률 60.6 · t 1.99 · p 0.427123 / 4월 n=67 · 평균 1.47 · t 2.83. CSV 는 소수 2자리로 반올림돼 있으므로 **CSV 자릿수까지** 대조(p 는 6자리) |
| C3 ✅ | Yahoo 월말 추가 수집(`period1/period2`, 수정전 Close, 월 키 정규화, 진행 중인 달 제외, **수익률로 잇기**, ASHR 대용·창업판 동결) + 신선도 | C1, C2, P0 | 2026-09 월 수익률이 10월 첫 영업일에 자동으로 붙고 `/data-operations` 에 보임 |
| C4 ✅ | API `/api/v1/market/seasonality` + 화면 `/market/seasonality`(히트맵·신호 카드·팝업) + 메뉴 | C2 | 와이어프레임 C 대로, 칸·막대 클릭 동작 |

### A 13F·내부자 (2단계)
| # | 티켓 | 선행 | 완료 기준 |
|---|---|---|---|
| A1 ✅ | SEC 마이그레이션(P1 번호) + `guru_roster`(23명 시드 · 퀀트 12곳 `kind='index'` 비활성) | P1 | 테이블 생성, 명단 35행 |
| A3a ✅ | SEC 클라이언트 통합 — `SEC_USER_AGENT` 필수(없으면 신선도 "SEC UA 미설정"), 프로세스 공용 속도 제한기(초당 ≤ 8), 백오프 | P0 | 4스레드 동시 호출에서도 초당 8 이하(테스트) |
| A2 ✅ | 원본 `filings.db` → Postgres 백필(거장 23명 13F 14.4만 행 · Form 4 · 13D/G · cusip_ref) + **정정공시 74묶음 표지 재수집 → `amendmentType` 반영** + **Form 4 과거분 보정**: 4/A 는 백필 중에 원 공시 거래를 대체, 공동 보고자 누락은 "과거분 알려진 공백"으로 표시(원문 재파싱은 선택) | A1, A3a | **SEC 대조로 빠진 30분기(버핏·Gayner·Icahn) 재수집, 0행 공시 2건 재확인 → 23명 × 분기 대조표가 SEC 와 일치**(§D-1) · 버크셔 2023Q3 = 153종목(152+1) pytest — **표지 XML 은 fixture 로 저장**(네트워크 없이 통과), 알려진 공동신고 1건 pytest, 품질 검사 기록 |
| A3b ✅ | 파서·수집기 이식(**공동 보고자 전부**, Form 4/A 대체, 계획매매 플래그, **13F `amendmentType` 파싱 — RESTATEMENT 대체 / NEW HOLDINGS 합산**) + 캐치업 루프 + 신선도 | A1, A3a, P0 | 새 Form 4 1건이 자동으로 들어오고 `/data-operations` 에 보임, NEW HOLDINGS 정정 fixture pytest |
| A4 ✅ | CUSIP 해소: OpenFIGI 단계 + `cusip_map` 캐시 | A2 | 거장 최근 분기 금액 기준 매핑 ≥ 95% |
| A5 ✅ | 거장 13F 화면 `/research/guru` + 분석 API(flows·consensus, collector 제거) | A2, A4 | 와이어프레임 A-1, 정족수 50% 규칙 |
| A6 ✅ | 내부자 거래 화면 `/research/insiders`(비파생 · P/S · 계획매매 제외만 순매수) + 공시 화면 링크 | A3b | 와이어프레임 A-2 |
| A7 ✅ | 거장 추가 UI(검색 → CIK → `backfill_status`) + 신규 거장 SEC 직접 백필(**2013Q2 부터**, A3b 의 `amendmentType` 규칙 그대로) | A3b | 새 거장 1명 추가 시 과거 13F 가 채워지고 정정공시가 합산/대체 규칙대로 |
| A8 ✅ | collector `guru13f*`·`inav.py` `/guru-13f/*` 프록시 삭제 + `apps/web/lib/api.ts` 잔여 참조 정리 | A5 | 참조 0, 테스트 통과 |

### B 실적 모니터 (3단계)
| # | 티켓 | 선행 | 완료 기준 |
|---|---|---|---|
| B1 ✅ | 실적 마이그레이션(P1 번호) + zip 안 `EARNINGS_MONITOR.db`·관전포인트 713행 중 내 보유·관심종목만 이관(펀드 열 제외) | P1 | 이관 행 수 기록 |
| B2 ✅ | LLM 래퍼(`llm_cli.py`+`web_fallback.py` 통합 → `claude -p` 절대경로·격리·도구 끔) + `llm` 큐(500초, 하루 상한, 오류 원인별 표시) | P0 | 8-K 표본 1건으로 관전포인트 왕복 성공, 로그아웃·사용량초과 시나리오 표시 확인 |
| B3a ✅ | Nasdaq 캘린더·EPS 컨센 → 화면에 바로 | B1 | 향후 4주 내 종목 발표가 EPS 컨센과 함께 보임 |
| B3b ✅ | Investing.com 크롤(화면 있는 크롬, Playwright 설치, 로그인 세션 조건 문서화, 실패 시 "매출 컨센 수집 실패") | B3a, P0 | ❓화면 잠금 상태에서 Cloudflare 통과 실측 → 매출 컨센 표시 |
| B4 ✅ | 8-K Ex.99.1·가이던스·세그먼트 파서 이식(A 의 SEC 클라이언트 공유) + **6-K 실적 경로(NBIS 등 외국 발행사)** + 발표 후 반응(토스, 30일 내 캐치업 가능) | A3a, B1 | 장후 발표 다음 날 아침 결과·반응 자동 |
| B5 ✅ | 관전포인트 생성(D-3) / 결과 판정 이식 | B2, B4 | 종목 상세에 ①~④ 와 결과 |
| B6 ✅ | `/stock/us` → `실적 모니터` 화면 교체(와이어프레임 B) + 고아 `earnings-card`·`/earnings/us` 프록시 삭제 | B3a~B5 | 화면 동작 |
| B7 ✅ | **`Ongoings/src/` 삭제**(사용자 지시) | B6 | 33파일 전부 "이식/버림/대체"로 분류됐고, 버림 파일이 zip 에도 있는지 확인한 뒤 |

## §D 데이터 무결성 점검 (2026-09-26, 실측)

### D-0 보간(interpolate) 원칙 — **어디에서도 보간하지 않는다**
빈 값을 추정으로 채우면 그 값이 실측처럼 통계·화면에 섞인다. 세 계획 모두 **빈 값은 빈 값으로 남기고,
그 사실을 화면에 적는다.** 구체적으로:
| 자리 | 빈 값이 생기는 이유 | 처리 |
|---|---|---|
| 계절성 월 수익률 | 원천에 그 달이 없음(항셍 1964~69 **16구간·17개월**, 각 지수 첫 달 `#N/A Requesting Data`) | 수익률 `NULL`. **빈 달 다음 달도 `NULL`** — 두세 달치 변화를 한 달 수익률로 세지 않는다. 통계 n 에서 빠진다 |
| 13F 분기 비교(QoQ) | 거장이 그 분기에 13F 를 **실제로 내지 않음**(Li Lu 2018Q4~2019Q3 4분기, Burry 8분기 — SEC 에도 없음 ✅) | 그 분기는 "미제출". **앞뒤 분기를 바로 비교하지 않는다**(편입/방출로 잘못 읽힘) |
| 13F 최신 분기 | 아직 안 냈거나 영영 안 냄(Ackman 최신 2026Q1, Burry 2025Q3 — SEC 와 일치 ✅) | 직전 분기 보유를 **이월하지 않는다**. "최근 분기 미제출 · 마지막 YYYYQn" 배지, 정족수 계산에서도 제외 |
| 내부자 월별 막대 | 그 달 거래가 없음 | 0 이 아니라 **막대 없음**(거래 없음과 0원 순매수는 다르다 — 매수=매도면 0) |
| 실적 결과 | 8-K 가 아직 안 나옴 / 크롤 실패 | "대기" / "수집 실패". 컨센을 실적 자리에 쓰지 않는다 |
| 발표 후 반응 | 그 시각 1분봉 없음(휴장·거래 없음) | 반응 `NULL` + 사유. 가까운 봉으로 당겨 쓰지 않는다(원본 `close_at_or_before` 는 **이전 봉**만 허용 — 유지) |

⚠️**계절성 이식 함정**: 원본은 지수 8개를 **한 달력(DataFrame 합집합 인덱스)** 에 올린 뒤 `pct_change(fill_method=None)` 을
하므로 빈 달이 자동으로 `NaN` 이 된다. 이식하면서 **지수별로 따로** 연속 행끼리 수익률을 내면 이 보호가 사라져
항셍 1964~69 의 2~3개월 변화가 1개월 수익률로 둔갑한다. → C2 에 "**완전 월 달력으로 reindex 후 계산**" + 항셍 pytest.

### D-1 누락·손실 — 원본 DB 만 믿으면 잃는 것
| 항목 | 실측 | 조치 |
|---|---|---|
| **13F: SEC 에는 있는데 원본 DB 에 없는 분기 30개** | 버핏 12(2013Q2~2016Q1) · Gayner 12 · Icahn 6(2013Q2~2014Q3) | A2 백필에 **"SEC 대조 후 빠진 분기 재수집"** 단계 추가. 백필 후 23명 × 분기 대조표가 SEC 와 같아야 완료 |
| 13F: 보유 행이 0인 공시 2건 | Gayner 2024Q4(0001096343-25-000011) · Hohn 2024Q2(0001647251-24-000007) | 정보표(infotable)를 SEC 에서 다시 받아 확인 — 진짜 0종목인지, 파싱 실패인지 |
| 13F: 원본 raw XML 을 안 가져옴 | 13F 799MB · 6-K 383MB | 손실 아님 — SEC 에서 언제든 다시 받을 수 있다(정정공시 표지 재수집이 그 예) |
| 13F: 퀀트·인덱스 12곳 | 전체 보유행의 92% | **사용자 결정으로 의도적 제외** — `guru_roster` 에 비활성으로 남겨 필요하면 켠다 |
| 실적: **NBIS 는 8-K 가 아니라 6-K 로 실적을 낸다** | 최근 1년 8-K 0 · 6-K 31 · 20-F(외국 발행사) | B4 파서에 **6-K 실적 보도자료** 경로 추가(원본에 `sixk_documents`·6-K 수집 흔적 있음). 안 하면 NBIS 실적이 영영 "대기" |
| 실적: ETF 보유 7종목 | SOXL·SCHD·TSL·GLD·XLB·EETH·BITO | 실적 발표가 없는 게 정상 — 화면에서 "ETF(실적 없음)"로 명시해 누락처럼 보이지 않게 |
| 실적: 이관 범위 | 원본 약 380종목 중 내 보유·관심종목만 | **의도적**(펀드 데이터 제외). 원본 zip 은 보관 |
| 계절성: 창업판 2026-09~ | 무료 원천 없음 | **사용자 결정으로 동결**, "갱신 중단" 배지 |
| 계절성: 각 지수 첫 달 | 엑셀 첫 행이 `#N/A Requesting Data` | 원본도 버림 — 동일(첫 달 수익률은 원래 계산 불가) |

### D-2 403·차단 위험 — 원천별 실측
| 원천 | 실측 | 위험 | 대응 |
|---|---|---|---|
| SEC `data.sec.gov` / `Archives` | 저장소 기본 UA·실제 연락처 UA → **200**, 파이썬 기본 UA → **403** | 중 — UA 가 빠지거나 초당 10회를 넘으면 **403 + IP 일시 차단** | `SEC_USER_AGENT` 필수(A3a), 공용 속도 제한 초당 ≤ 8, 403 이면 **즉시 멈추고 10분 뒤 재개**(연타 금지) |
| SEC `browse-edgar`(거장 검색) | 200 | 낮음 | 거장 추가할 때만 호출 |
| Nasdaq `api.nasdaq.com` | 브라우저 UA → 200, 파이썬 UA → **응답 없이 시간초과**(Akamai 가 조용히 붙잡음) | **중 — 403 이 아니라 '무응답'이라 실패로 안 보인다** | 브라우저 UA·Accept 헤더 고정, 타임아웃 20초, 시간초과를 **차단 신호**로 집계해 신선도에 "Nasdaq 응답 없음" |
| Investing.com | Cloudflare 앞단(`cf-ray`). 평문 GET 은 200 HTML 이지만 실제 표는 JS 로 채워짐 · 원본은 헤드리스 차단 뒤 화면 있는 크롬 사용 | **높음** | 하루 1회만, 실패 시 "매출 컨센 수집 실패"(EPS 는 Nasdaq 로 계속). ❓화면 잠금 실측(B3b) |
| Yahoo `query1` chart | 브라우저 UA → 200, 파이썬 UA → **429**(Edge 요청 제한) | 중 | 브라우저 UA(기존 `history.py` 와 동일) · 월 1회 호출이라 양 자체는 적음 · 429 면 다음 날 캐치업 |
| Yahoo `quoteSummary` | crumb 을 받아도 **429** | — | 계획에서 쓰지 않음 |
| Stooq | JS 봇 챌린지 | — | 계획에서 쓰지 않음 |
| OpenFIGI(무키) | 200, `ratelimit-limit=25`/분 | 낮음 | 분기에 새 CUSIP 만, 요청당 10건 → 분당 250건. 429 면 1분 대기 |
| 토스 OpenAPI | 인증형, 실측 한도 20 req/s(기존 코드 주석) | 낮음 | 기존 `min_interval=0.12` 그대로 |

### D-3 C·A·B 티켓에 추가되는 완료 기준
- **C2**: 완전 월 달력 reindex 후 수익률 계산 · 항셍 1964~69 빈 달 pytest(빈 달·다음 달 모두 NULL).
- **A2**: SEC 대조로 빠진 30분기 재수집 · 0행 공시 2건 재확인 · **23명 × 분기 대조표 = SEC** 가 완료 조건.
- **A5**: 미제출 분기 건너뛴 QoQ 금지 · 최신 분기 미제출 배지 · 정족수에서 제외.
- **B4**: 6-K 실적 경로(NBIS).
- **공통(P0)**: 원천별 "차단 신호"(403 / 429 / 무응답 시간초과)를 구분해 `/data-operations` 에 표시, 차단이면 백오프 후 재개.

## 진행 기록

### P0 ✅ 완료 (2026-09-26)
- **DB**: `0019_job_queues` — `jobs.queue`(기본 `default`) · `heartbeat_at` · `attempts`, 인덱스 `(queue,status,created_at)`,
  표 `source_status`. 로컬 DB 적용(0018 → 0019), 기존 작업 12건은 `default` 로.
- **worker**(`apps/worker/main.py`): `WORKER_QUEUES`/`WORKER_NAME` 환경변수, 큐별 `claim_job`, 작업 중 30초 심장박동
  스레드, 5분 끊긴 RUNNING 을 PENDING 으로 되살림(3회 넘으면 FAILED), 30초마다 생존 신호.
  `source_health.py` — 실패 종류(403/429/timeout/other) 분류·기록.
- **API**: `GET /api/v1/jobs/sources`(worker 는 2분 안 생존 신호 → alive, 원천은 마지막 실패 종류).
- **화면**: `/data-operations` 에 `수집기` 칸(예: "2/2 작동", 원천 경고 수) → 누르면 원천별 표.
  덤: `AnimatedNumber` 가 공백을 접던 버그 수정("2/2작동" → "2/2 작동").
- **실행**: `scripts/workers/install.sh [install|uninstall|status]` → LaunchAgent 2개
  `com.personal-investment.worker.{sec_crawl,llm}`(gui 도메인, KeepAlive, 로그 `~/Library/Logs/personal-investment/`).
- **검증**:
  - pytest: worker 148(신규 8) · api 258(신규 1) 통과.
  - 실 DB 연기 테스트: 두 큐 TEST_JOB 각자 처리 · 심장박동 10분 끊긴 작업 자동 부활(시도 2회째 SUCCESS) · 14초 안에 전부 끝.
    (테스트 행 3건은 확인 후 삭제)
  - `kill -9` 로 llm worker 를 죽이자 launchd 가 새 pid 로 다시 띄움.
- **맥 덮개**: 사용자 결정 = 클램셸(전원 + 외부 모니터). 세션 동안 `caffeinate -ims` 가 잠자기를 막는다.
  ⚠️LaunchAgent worker 는 맥이 **잠들면** 멈춘다(깨면 이어서 돈다 — 캐치업 설계라 놓친 일은 다음에 따라잡는다).

### C1 ✅ 완료 (2026-09-26)
- `0020_seasonality`: `seasonality_series`(19행: 지수 8 · 섹터 11, 원본 이름·블룸버그 티커·Yahoo 심볼·이어붙이기 방식
  direct/proxy/frozen) · `monthly_closes`(series, 'YYYY-MM', close, source). 시드 목록: `database/seeds/seasonality_series.py`.
- 파서 `app/core/seasonality_io.py`(원본 `load_prices` 이식) · 적재 `scripts/seed_seasonality_bloomberg.py`
  (**원본 n 과 대조해 하나라도 어긋나면 적재 거부**, `--dry-run`).
- 결과: **19개 전부 원본 전구간 n 합과 일치**(SPX 798 · HSI 711 = 빈 구간 16개를 건너뛴 값 · IT 443 …) →
  `monthly_closes` 9,002행(1960-02 ~ 2026-08, 전부 `bloomberg`).
- pytest: api 261(신규 3 — BDH 잔재 행 건너뛰기, 빈 달 안 채움, 빈 달 건너편은 쌍이 아님, 월초/월말 같은 키) · worker 148.

### C2 ✅ 완료 (2026-09-26)
- `apps/api/app/core/seasonality.py`: 원본 `tstat`·`pvalue`(Student-t)·`tercile_band`·`signal`·`hit`·`proof_table`(BH-FDR)·
  `walk_forward`·`next_month_signals` 이식. 추가: `monthly_returns`(빈틈없는 월 달력 → 빈 달·다음 달 NaN),
  `evidence()`(근거 없음 판정), 전역 `MIN_N` 변경 대신 `need_base` 인자.
- 의존성 고정(`apps/api/requirements.txt`): pandas 2.2.3 · numpy 2.1.3 · scipy 1.14.1 · openpyxl 3.1.5.
- **원본 산출물 전량 재현**(`scripts/verify_seasonality_port.py`, DB 적재분으로 계산):
  `seasonality_stats.csv` 288행 · `signals_history.csv` 12,474행 · `sector_stats.csv` 396행 · `sector_signals.csv` 14,484행
  — **27,642행 모두 한 글자도 다르지 않음.**
- pytest: api 265(신규 4 — 원본 `_selfcheck` 전부, 단일 지수에서도 빈 달 다음 달 NaN, 근거 없음 판정).

### C3 ✅ 완료 (2026-09-26)
- `0021_monthly_closes_source_pk`: 키를 (series, month, **source**) 로 — 전환 달(2026-08)의 블룸버그·Yahoo 값을 둘 다 둔다.
- worker 핸들러 `SEASONALITY_APPEND`(sec_crawl 큐): Yahoo `period1/period2`·`interval=1mo`·수정전 close·
  **거래소 현지 시각으로 달 판정**·진행 중인 달 제외·같은 달 마지막 값. 전환 달 12개월 전부터 받는다.
- API 캐치업 `app/core/seasonality_sync.py`(lifespan, 30분마다): 지난달(KST) Yahoo 값이 빠진 시계열이 있으면 작업을
  넣는다. PENDING/RUNNING 이면 안 넣고, 6시간 안에 넣은 적 있으면 안 넣는다. `chained_returns()` — 원천 안에서만
  수익률을 내고 전환 달 다음부터 Yahoo 로 잇는다.
- **실측으로 잡은 버그**: 처음엔 UTC 로 달을 정해 **아시아 지수가 한 달씩 밀렸다** — 겹침 12개월 월수익률 차이
  코스피 평균 19.7%p · 코스닥 14.8%p · 항셍 8.2%p(미국 0). Yahoo `exchangeTimezoneName` 으로 고친 뒤 **전부 0.000**.
  잘못 들어간 237행은 지우고 다시 받음.
- **겹침 12개월 월수익률 차이(블룸버그 vs Yahoo)** — 대용 품질 기록:

  | 시계열 | Yahoo | 평균 \|Δ\| %p | 최대 %p |
  |---|---|---|---|
  | SPX·CCMP·RTY·KOSPI·KOSDAQ·HSI·SOX | 지수 그대로 | 0.000 | 0.000 |
  | CSI300 | ASHR | 0.663 | 1.852 |
  | **COMM** | XLC | **3.463** | **13.329** |
  | **IT** | XLK | **1.548** | **4.511** |
  | **COND** | XLY | **1.217** | **3.117** |
  | ENRS·UTIL·HLTH·FINL·CONS·INDU·MATR | SPDR | 0.13~0.65 | 0.26~1.63 |
  ⚠️XLC·XLK·XLY 는 대형주 **비중 상한**(GOOGL·META / AAPL·MSFT·NVDA / AMZN·TSLA)이 있어 지수와 구조적으로 다르다 → 사용자 결정 7.
  → **결정 7: 세 섹터 동결**(2026-09-26). 원본 재현 27,642행은 동결 뒤에도 그대로 일치, 캐치업 판정 정상(추가 작업 없음).
- 실행: 캐치업 루프가 넣은 작업을 sec_crawl worker 가 처리(18개 시계열, 실패 0), `/data-operations` 에 `yahoo 정상`.
- pytest: worker 152(신규 4 — 진행 중인 달·빈 값·중복, 아시아 시간대, 시차 대체) · api 270(신규 5 — KST 지난달,
  원천 전환 잇기, 작업 넣기·중복 방지·6시간 백오프).
- ⚠️운영 메모: API(`--reload`)가 새 핸들러를 가진 worker 보다 먼저 재기동되면 옛 worker 가 "Unknown job type" 으로
  실패시킨다(한 번 겪음 — 행 삭제 후 재실행). 새 작업 종류를 더할 땐 **worker 먼저 재시작**.

### C4 ✅ 완료 (2026-09-26) — 계절성 C 계획 전체 완료
- API(`app/api/seasonality.py`, 새 라우터 — 사용자 수정 중인 `market.py` 는 건드리지 않음):
  `GET /api/v1/market/seasonality?window=전구간|10년|5년`(그룹별 히트맵 칸·이번 달 신호(`evidence`)·백테스트+'항상 상승' 기준선),
  `GET /api/v1/market/seasonality/cell?series=&month=`(연도별 수익률). 캐시 키 = (구간, 마지막 적재 시각) — 첫 계산 0.76초, 이후 0.02초.
- 화면 `/market/seasonality`(메뉴 `시장 모니터링 > 계절성`): 위 칸 4(근거 있는 신호 수 · FDR 유의 칸 · SOX 이번 달 과거 ·
  섹터 1위/꼴찌) / 히트맵(지수·섹터 칩, 구간 칩, 이번 달 테두리, ★) → 칸 누르면 연도별 막대 / 이번 달 신호(근거 없음 회색,
  갱신 중단·대용 배지) / 전체 목록 = 백테스트(표본 내 경고, 중립 1/3 상한).
- 공용 `SignedBarChart` 에 `unit`·`formatLabel` 선택 인자(기본값 그대로 — 기존 화면 영향 없음).
- 실데이터에서 드러난 것: 지수 백테스트 '상승' 적중 55.8% < **항상 상승 57.4%**, 섹터 57.9% < **58.6%** — 화면은 이 비교를 그대로 보여 준다.
- 검증: pytest api 273(신규 3) · worker 152, 1440×900 한 화면(세로 스크롤 0), 칸·칩·팝업 클릭 확인, 콘솔 에러 0.

### A1 ✅ 완료 (2026-09-26)
- `0022_sec_filings`: `guru_roster` · `sec_filings`(+`amendment_type`) · `holdings_13f` · `form4_transactions`(+`superseded_by`) ·
  `ownership_events` · `cusip_map`(+`figi`, confidence 'openfigi'). 원본 열 이름 유지, 날짜는 date/timestamptz, summary 는 JSONB.
- 명단 시드 `database/seeds/guru_roster.py`(원본 watchlist.json 에서 추출) + `scripts/seed_guru_roster.py`(업서트, 사용자가 바꾼
  active·backfill_status 는 덮지 않음). 로컬 적재: **거장 23 활성(백필 대기, 2013-04-01 부터) · 인덱스 12 비활성(skip)**.
  ⚠️계획 초안의 "퀀트·인덱스 11곳"은 **12곳**이었다(원본 목록 12개 — 버크셔가 role=issuer 로 따로 있어 셈이 한 칸 밀렸다). 문서 4곳 정정.
- 검증: pytest api 274(신규 1 — 23+12·CIK 10자리·중복 없음) · worker 152, 시드 두 번 돌려 같은 결과.

### A3a ✅ 완료 (2026-09-26)
- `apps/worker/sec/client.py`: 스레드 안전 `RateLimiter`(**프로세스당 초당 4회** — SEC 를 부르는 프로세스가 API·sec_crawl worker
  둘이라 합계 ≤ 8, `SEC_RATE_PER_PROCESS` 로 조정), `sec_get`(429·5xx → 1·2·4초 백오프, **403 → 그 프로세스 SEC 요청 10분 전면 정지**,
  정지 중엔 SEC 에 닿지 않고 `SecBlocked`), `required_user_agent()`(새 수집 작업용 — 없으면 `SecConfigError`).
- 기존 `prices/filings.py`(공시 화면)도 이 클라이언트를 거친다 — 예전엔 4스레드가 제한 없이 불렀다. 403 이면 종목 칸에
  "SEC 403 차단 — 10분 쉰 뒤 다시". 공시 화면 기본 UA 는 그대로(개인 이메일을 말없이 보내지 않는 기존 원칙).
- sec_crawl worker 는 `SEC_USER_AGENT` 가 없으면 `/data-operations` 에 **`sec · 설정 필요`**(새 실패 종류 `config`)를 남긴다.
  `run-worker.sh` 가 `.env.local` 의 `SEC_USER_AGENT` 를 읽는다.
- ⚠️사고 1건: `run-worker.sh` 에서 `.env.local` 에 줄이 없을 때 `grep` 이 1 을 돌려 `set -eo pipefail` 로 스크립트가 죽었다 →
  **두 worker 가 약 1분(21:59:52~22:01:03) 재시작 루프**. `|| true` 로 고치고 재기동 확인(주석으로 남김).
- 검증: pytest worker 158(신규 6 — 간격·403 정지·정지 중 무호출·429 백오프·404·UA 필수·4스레드 합계 속도) · api 274,
  공시 화면 정상(15종목, source_ok), `/jobs/sources` 에 `sec config` 표시.
- **다음(A2) 전 사용자 결정 필요**: `SEC_USER_AGENT` 값(연락처). A2 는 SEC 에서 빠진 30분기·정정 표지 74건을 받아야 한다.

### A2 ✅ 완료 (2026-09-26)
- `scripts/backfill_sec_from_filings_db.py [--reset] [--offline]` — 1) 원본 이관 2) 거장 SEC 대조 3) Form 4/A 4) 대조 보고.
- **1) 원본 이관**: 거장 13F 공시 1,083 · 보유 **143,873**(실측과 일치) · Form 4/13D/13G 공시 13,568 · Form 4 거래 48,363 ·
  13D/G 200 · CUSIP 11,323. 미래 날짜 Form 4 1건(GOOGL 2027-01-25, 0001193125-26-025268) — 보관, 품질 경고.
- **2) 거장 SEC 대조**(SEC 제출 목록·표지 사용):
  - 원본이 '13F' 로만 적은 공시 중 **39건이 실제로 13F-HR/A** — 양식 복원. 정정 43건 전부 종류 확인:
    **NEW HOLDINGS 23 · RESTATEMENT 20 · 모름 0**.
  - **SEC 에 있고 원본에 없던 공시 34건 새로 받음**: 빠진 분기 30개(버핏 12 · Gayner 12 · Icahn 6) + 그 분기들의 추가분 정정 4건
    (버핏 2013-06·2014-09·2015-06, Gayner 2014-12).
  - 원본에서 보유 0행이던 2건은 **실제로는 0 이 아니었다**(파싱 실패) — Hohn 2024Q2 **10행**, Gayner 2024Q4 **214행** 다시 받음.
  - **거장 23명 × 분기가 SEC 와 전부 일치**(불일치 0).
- **3) Form 4/A**: 추적 기업 22곳의 SEC 목록에서 4/A 355건 확인, 그중 원본에 있던 100건의 양식을 '4/A' 로 복원,
  같은 (발행사·내부자·거래일·코드)의 앞선 거래 **358행에 `superseded_by`** — 이중 집계 제거.
  공동 신고의 나머지 보고자(원본 파서가 첫 보고자만 읽음)는 **과거분 알려진 공백**으로 둔다 — 새 공시는 A3b 파서가 전부 읽는다.
- **4) 대조**: **버크셔 2023Q3 = 153종목**(원본 152 → RESTATEMENT 152 가 대체 → NEW HOLDINGS 1 더함) — SEC 실제 표지로 확인,
  pytest(`test_guru13f.py`)의 가정과 같다. 완료 조건 통과 → 거장 23명 `backfill_status='done'`, `/data-operations` 에 `sec 정상`.
- 소요: 수 분(프로세스당 초당 4회), 403 없음.

### A3b ✅ 완료 (2026-09-26)
- **파서** `apps/worker/sec/ownership.py`: `parse_form4` — ★공동 신고 보고자 **전원**(원본은 첫 보고자만).
  거래 행은 보고자 수만큼 복제하지 않는다(펀드+운용역이 같은 지분을 함께 신고 → 복제하면 순매수가 곱해진다) —
  `insider_name` = "A; B", `summary_json.owners` = 전원 목록. 코드표·10b5-1(각주·`aff10b5One`)·파생 표 유지.
  `parse_13dg` — 구조화 표지(2024-12~) 관용 추출, `MM/DD/YYYY` 날짜, CUSIP 태그 `issuerCusipNumber`(실측).
- **수집기** `apps/worker/handlers/sec_collect.py` — 작업 `SEC_13F` · `SEC_FORM4` · `SEC_13DG`(큐 sec_crawl).
  submissions 최근 목록 → DB 에 없는 접수번호만 → **오래된 것부터** 적재. 13F-HR/A 는 표지 `amendmentType` 기록.
  Form 4 대상 = 기존 추적 22곳 + 내 미국 보유 + 관심종목(`company_tickers.json`) → 실측 30곳. 조회 기간 180일.
  **4/A 대체는 순서와 무관**: 4/A 가 들어오면 같은 (발행사·내부자·거래일·코드)의 다른 행을, 원 공시가 늦게
  들어오면 그 새 행을 대체 표시(실측: ONTO 2026-09-04 — 4/A 가 원 공시보다 앞 접수번호).
  신선도는 `source_status` 의 `sec_13f` · `sec_form4` · `sec_13dg`(→ /data-operations), 403·config·timeout 종류별.
- `sec_get`: 응답 시간 초과도 1·2·4초 재시도(실측: 문서 하나의 timeout 으로 한 회차 전체가 실패).
- **캐치업 루프** `apps/api/app/core/sec_sync.py`(API lifespan, 5분 확인): Form 4 뉴욕 월~금 1시간 · 13D/G 12시간 ·
  13F 시즌(분기말 +30~50일) 매일, 그 밖 주 1회. 진행 중이면 안 넣고, 실패도 주기를 지킨다.
- **실측 결과**: Form 4 **434건 새로 들어옴**(최신 접수 2026-09-25, 공동 신고 4건 — 버크셔+버핏 LEN 매수 등),
  4/A 대체 1건 · 13D/G 71건(71건 모두 파싱, CUSIP 71/71) · 13F 0건(Q3 시즌 전 — 정상).
  `/api/v1/jobs/sources` → sec_form4·sec_13dg·sec_13f 모두 ok.
- 테스트: worker 175(+12: 파서 5 · 수집기 6[NEW HOLDINGS 정정 fixture, 4/A 양방향 대체, 13D/G, UA 없음=config,
  403 기록] · timeout 재시도 1) · api 280(+3 주기 판정).
- ⚠️운영 메모: ① 새 작업 종류를 추가할 때 API(--reload)가 먼저 작업을 넣어 구 worker 가 "Unknown job type" 으로
  실패시킨 일이 **또** 있었다 — 행 삭제로 정리. 순서: **worker 재시작 → API 코드**. ② 맥이 **배터리 + 덮개 닫힘**이면
  클램셸 모드가 아니라 잠든다(pmset 실측 — 22:39~23:21 잠듦, 그동안 13D/G 작업이 멈췄다가 깨며 timeout).
  전원 연결 + 외부 모니터일 때만 계속 돈다. 깨어나면 캐치업 루프가 따라잡는다.

### A4 ✅ 완료 (2026-09-27)
- `apps/worker/sec/cusip.py` — 원본 `CusipResolver` 이름 정확·유일 일치(`norm_name`·`unique_name_map`) 이식 +
  **OpenFIGI** 단계(무키 분당 25요청 · 요청당 10건, 429 → 1분 대기, 끊김·시간 초과 재시도). 미국 통합 상장
  (`exchCode='US'`) 우선, `BRK/B` → `BRK-B`. ★첫 글자가 영문인 코드는 **CINS** 로 묻는다 — `ID_CUSIP` 으로는
  ASML(N07059210)·네비우스(N97284108)·시게이트(G7997R103)를 못 찾았다(실측). 소문자 CUSIP(`48251w104` KKR)은 대문자로.
- 작업 `CUSIP_RESOLVE`(큐 sec_crawl, `handlers/cusip_resolve.py`) — 대상은 `cusip_map` 에 없거나 티커 없고 아직
  안 물어본 CUSIP(`figi IS NULL`), **최근 분기 · 큰 금액부터**. "물어봤지만 없음"은 `figi=''` 로 남겨 다시 묻지 않는다.
  우선순위 manual > openfigi > exact > none — 이미 붙은 티커·수동 보정은 덮지 않는다. 10건마다 커밋(중간에 죽어도 보존).
  API `sec_sync` 가 하루 1회 넣는다(새 CUSIP 없으면 바로 끝). 신선도 `source_status.openfigi`.
- **실측**: 4,060건 조회 → openfigi 2,639 · exact +172 · none 7,186(대부분 옛 분기의 청산·채권 등).
  거장 23명 최근 분기 금액 기준 매핑률 **68.8% → 99.91%**(미매핑 $0.6B / $661.5B, `scripts/cusip_coverage.py` —
  정정 규칙 · 금액 단위 보정 · SH 만). 남은 최대는 Orla Mining 68634K106($568M, Prem Watsa 78.5% 의 원인) — A5 에서 이름만 표시.
- 테스트: worker 181(+6: 결과 고르기 · 이름 충돌 · 캐시/우선순위 · 429 · 끊김/시간 초과 재시도 · CINS/소문자),
  api 280(주기표에 CUSIP_RESOLVE).
- ⚠️운영: 맥이 배터리로 잠든 동안 이 작업이 10시간 넘게 조금씩만 진행됐다(첫 두 회차는 깨며 timeout ·
  "Server disconnected" 로 실패 → 끊김 재시도 추가). 사용자가 깨운 뒤 약 15분에 끝났다. 전원 어댑터가 연결돼도
  `pmset -g batt` 가 "No adapter attached" 였다 — 충전기 인식 확인 필요.

### A5 ✅ 완료 (2026-09-27)
- **분석 코어** `apps/api/app/core/guru_flows.py` — 원본 `guru_flows.py`(동시 편입/방출 · 동시 리밸런싱 gross/net/agreement ·
  섹터 이동 · 분기별 커버리지) 이식 + 내 보유 × 거장 · 종목별 거장 비중 추이(신규). 불러온 데이터를 받는 **순수 함수**.
  바꾼 것: ① 정정공시 = `effective_accessions`(원본 `_LATEST_13F_CTE` 버그 제거) ② 금액 단위 **공시마다** 보정 후 합산
  (원 공시 천 달러 + 추가분 달러) ③ 채권(PRN)도 제외 ④ 거장 수는 명단에서. 정족수 50% 미달 분기는 비교 제외,
  미제출 분기 **이월 없음**(추이 표에서 빈칸), 두 분기 모두 낸 거장만 변동 계산. 기준선(baseline) 백분위는 옮기지 않았다(화면 요구 없음).
- **API** `apps/api/app/api/guru.py`: `/api/v1/research/guru/overview` · `/quarter?period=` · `/stock?ticker=`.
  캐시 키 = (13F 공시 최대 id, cusip_map 갱신, 명단 수). 응답마다 `disclaimer`(예측 아님 · 24조합 통과 0).
- **화면** `/research/guru`(nav `리서치 > 거장 13F`) — 와이어프레임 A-1: 위 칸 4개(제출 21/23 · 91% 정족수 통과 → 제출 현황
  팝업[미제출 · 마지막 분기 배지] / 여럿이 새로 산 41 / 여럿이 전량 판 27 / 내 보유 11/15), 왼쪽 **분기별 섹터 순유입**
  (새 `SignedStackedBarChart` — 양수는 위로 · 음수는 아래로 쌓기, 막대 → 그 분기 새로 산/전량 판/동시 조정/섹터 탭),
  오른쪽 **내 보유 × 거장**(행 → 거장별 8분기 비중 추이). 칸마다 "예측 아님".
- ★**섹터 커버리지**: 원본 수기 CSV(286 CUSIP, 2026-03-31 상위 종목)는 분기가 지나며 낡아 26Q2 커버리지 86% ·
  미분류가 가장 큰 조각(+489bp)이었다. → **마이그레이션 0023**(`cusip_map.sic` · `sector`) + `CUSIP_RESOLVE` 에
  `fill_sectors` 단계(티커 → CIK → SEC submissions 의 SIC → `sec/sic.py` 로 한글 GICS 식 섹터, CSV 가 먼저 · SIC 는 빈칸만,
  `sic=''` = 없음). 실측 2,733개 회사 조회 → 2,923 CUSIP 채움. **커버리지 80~91% → 96.5~99.5%**, 26Q2 미분류 +489 → −5bp.
  (번호: 0023 을 여기서 가져가 실적은 0024 — P1 표 갱신.)
- 실측 해석 메모: 25Q1 필수소비재 +425bp 는 거의 전부 Burry 의 EL — 그 분기 Scion 13F 는 풋 6종목 + 롱 EL 1종목이라
  옵션을 빼면 롱 북이 EL 100% 다. 거장 동일가중 평균의 성질(원본과 같은 규칙)이라 그대로 둔다.
- 테스트: api 289(+9: 정족수 · 미제출 제외 · gross/net/agreement · 단위 · 섹터 커버리지 격차 · CSV 우선/SIC 대체 ·
  내 보유 클래스 합침 · 이월 없음 · 불러오기[NEW HOLDINGS + 천 달러/달러 + 옵션·채권 제외]),
  worker 183(+2: SIC 범위 · 회사당 1회 조회/캐시). 웹 tsc 통과, 1440×900 화면·팝업 3종 브라우저 확인.
- collector 프록시(`/guru-13f/*`)와 사본 삭제는 A8.

### A6 ✅ 완료 (2026-09-27)
- **API** `apps/api/app/api/insiders.py`: `/api/v1/research/insiders/overview` · `/month?month=YYYY-MM`. 대상 = 내 미국 보유 +
  관심종목(티커 별칭 GOOG↔GOOGL). **순매수 = 비파생 · 코드 P/S · 10b5-1 계획매매 아님 · 정정 대체분 아님 · 미래 날짜 아님**.
  월 상세는 **모든** Form 4 거래를 주고 제외분에 이유(계획매매 · 보상 부여 · 옵션 행사 · 세금 · 증여 · 파생 · 정정 대체 · 미래 날짜).
  거래 없는 달은 `net_value=null`(막대 없음 — 0원 순매수와 다름). 종목별 **수집 시작일**(`data_from`)과 Form 4 없는 종목(ETF 7개)을 준다.
  13D 는 **내 종목이 대상인 것만** — 실측: 템퍼스가 퍼스널리스 지분을 신고한 13D/A 가 잡혀 있었다(내 종목이 제출자) → 제외.
  백필 행은 issuer_cik 에 제출자 CIK 가 있어 대상 이름 첫 단어로도 맞춘다.
- **화면** `/research/insiders`(nav `리서치 > 내부자 거래`) — 와이어프레임 A-2: 위 칸 90일 순매수* −$1.49B · 장내 매수 0건 ·
  여러 임원 동시 매수 0 · 최근 13D 없음 / 월별 순매수* 24개월(종목별 누적, `SignedStackedBarChart` 재사용 — `unit` 추가) →
  막대 → 그 달 거래표(센 것 위, 제외분 회색 · 계획매도 "계획" 배지). 수집 시작이 늦은 종목(CRWV 25.03~ · GLW/NBIS 26.03~ ·
  AMD/TEM 26.04~ · HUT 26.05~)과 미래 날짜 1건 제외를 카드 아래에 명시.
- 기존 `공시` 화면의 "내부자 서식" 칸 → `내부자 거래` 화면으로 이동(설명 팝업은 다른 버튼으로 그대로).
- 실측 확인: 26.09 NVDA −$818M 은 이사 Mark Stevens 의 장내 매도 — 원문 `aff10b5One=0` · 10b5-1 각주 없음 = 계획매매가 아닌
  재량 매도라 세는 게 맞다. 같은 달 제외 303건 중 계획매도 156 · 보상 66 · 파생 54.
- 테스트: api 293(+4: 제외 규칙 · 월 키 · 순매수/매수/동시 매수/13D 대상 · 월 상세 제외 이유). conftest 에 watchlist_items 비우기 추가.
  웹 tsc 통과, 1440×900 화면·월 팝업 브라우저 확인.

### A7 ✅ 완료 (2026-09-27)
- **검색** `apps/api/app/core/sec_search.py` — 원본 `InvestorResolver` 이식: EDGAR `browse-edgar?type=13F-HR`(13F 제출자만),
  한 곳 일치(회사 페이지)/여러 곳(목록 표) 둘 다 파싱. ⚠️**운용사 이름**으로만 찾아진다(실측 "einhorn" 0건, "greenlight" 1건).
  API 설정에 `SEC_USER_AGENT` 추가(worker 와 같은 값, 없으면 503 "SEC UA 미설정").
- **API** `/api/v1/research/guru/roster`(GET · POST 추가 · PATCH `{active}`) · `/search?q=`. 추가 = `kind='guru'`, `pending`,
  `SEC_13F_BACKFILL` 작업 예약. 비활성·인덱스 기관은 "다시 켜기"(백필 안 됐으면 백필도). 끄면 데이터는 남고 분석에서만 빠진다
  (분석은 active 거장만 — A5 에서 거장 수를 명단에서 세게 해 둔 것이 그대로 쓰인다).
- **worker** `SEC_13F_BACKFILL`(`handlers/sec_collect.backfill_guru`): submissions 최근 목록 + **과거 페이지 전부** →
  `backfill_from`(2013-04-01) 이후 13F-HR/A → A3b 와 같은 적재(`store_13f` 로 공통화 — `collect_13f` 도 이걸 쓴다) ·
  /A 는 표지 amendmentType. 상태 pending → running → done | failed(note). 끝나면 CUSIP_RESOLVE 를 바로 예약.
  `sec_sync` 가 작업 없이 남은 pending 거장을 다시 넣는다(추가 직후 API 가 죽은 경우).
- **화면** `/research/guru` 제출 현황 팝업 → **+ 거장 추가 · 관리**(`guru-manager.tsx`): 검색 → 화면 이름 → 추가,
  명단(13F 분기 수 · 마지막 분기 · 백필 상태 배지 · 켜짐/꺼짐). 백필 중에는 5초마다 새로 고침.
- **실측**(실제 화면에서 추가): Greenlight Capital(David Einhorn, CIK 0001079114) → 백필 43분기 · 공시 47건 · 정보표 없음 0 —
  **SEC 목록과 일치**(13F-HR 43분기 · HR/A 4건, 2013-06 ~ 2023-12). 정정 4건 = RESTATEMENT 1 · NEW HOLDINGS 3 →
  2014Q1 대체(127행, 합치면 254) · 2013Q3 95+3 · 2017Q3 119+3 합산 확인. 추가 중 화면의 거장 수 24 · 제출률 21/24 로 바로 반영.
  ⚠️사용자 결정 1(거장 23명)에 따라 **검증 후 이 시험 거장은 명단 · 공시 47 · 보유행 5,126 을 지웠다**(cusip_map 캐시는 남김) → 23명 복원.
- 테스트: worker 185(+2: 과거 페이지 · 2013Q2 이전 제외 · NEW HOLDINGS · done + CUSIP 예약 / 403 → failed),
  api 297(+4: 검색 파싱 · 추가/중복 409 · 인덱스 승격 · 켜기/끄기 · 고아 pending 재예약). 웹 tsc 통과.

### A8 ✅ 완료 (2026-09-27) — 계획 A(13F·내부자) 전체 완료
- **삭제**(모두 git 추적 파일 — 되돌릴 수 있음): `apps/collector/collector/{guru13f, guru_flows, guru_queries}.py` ·
  `assets/guru_sector_map.csv`(API `app/assets/` 로 옮겨 둠) · `apps/collector/tests/test_guru_flows.py`.
  collector `main.py`: `Guru13F` import · 서비스 생성 · `/guru-13f/{roster, portfolio, changes, timeline, consensus, flows,
  turnover}` 7개 · refresh 루프 제거(`main.py` 의 다른 미커밋 수정은 건드리지 않음). API `inav.py` 의 `/guru-13f/*` 프록시 7개 제거.
  `apps/web/lib/api.ts` 의 고아 타입 `Guru13fFlowGuru` · `Guru13fPeriodMeta` · `Guru13fFlowBase` 제거(쓰는 곳 0).
  `docker-compose.yml` 의 원본 `filings.db` 마운트(`/srv/legacy/guru13f_db`) 제거.
- `docs/guru-13f-flows.md` 머리에 "배관은 삭제, 분석은 API 로 이전" 안내 — 본문은 방법론 기록으로 남김.
- **참조 0**: 옛 모듈·경로 이름 전체 검색 → 남은 것은 새 API 모듈(`app/core/guru13f.py` · `guru_flows.py` · `api/guru.py`)과
  그 사용처뿐. collector `main.py` 에 guru 이름 0(AST 확인).
- 원본 collector 의 consensus · turnover 는 옮기지 않았다 — 쓰는 화면이 없었고(`track-record/guru-13f` 는 이미 삭제된 상태),
  A5 화면은 동시 편입/방출 · 동시 조정 · 섹터로 대신한다.
- 테스트: api 297 · worker 185 · collector 84(1 skip — 삭제한 test_guru_flows 9개 빠짐) · 웹 tsc 통과.

### B1 ✅ 완료 (2026-09-27)
- **마이그레이션 0024**(`0024_earnings`): `earnings_events`(ticker·quarter 고유, 일정 · 장전/장후 · EPS/매출 컨센 · 매출 컨센
  상태 `ok`/`failed` · 원천) · `earnings_results`(실적 · 서프라이즈 · 판정 · 8-K · 발표 후 반응 · 원본 반응 요약) ·
  `earnings_guidance` · `earnings_watchpoints`(ticker·quarter·rank 고유). 모델 추가 · API 시험 DB 비우기 목록에 추가.
  ⚠️`quarter` 는 원본 `derive_fiscal_quarter` 규칙의 **발표일 기준 달력 분기 라벨** — 회사 회계분기 아님(NVDA 8월 = 2026Q2).
- ⚠️**원천 변경**: `EARNINGS_MONITOR.db` 는 zip 에 **없다**(zip 의 .db 는 Thumbs.db 뿐) — 원본 경로는 사내 경로(비공개)
  (`raw\data\_데이터베이스\`, `segment_store.py:21`). 그런데 원본에서 **엑셀이 정본, DB 는 미러**였다
  (`earnings_store.mirror_master_to_db`) → zip 안 `input/processed/보유종목정리.xlsx` 에서 옮긴다(잃는 것 없음).
- **이관** `scripts/import_earnings_workbook.py`(파싱은 `app/core/earnings_import.py`): 대상 = 내 미국 보유 + 관심종목
  (GOOG → GOOGL). `실적`·`과거` 시트 → 발표 19건(10종목 × 최근 2분기, ETF 7종목은 원본에도 없음) · 결과 19 ·
  `관전포인트` 시트(우선) + 실적 시트 관전포인트1~4(빈 칸만) → 70행. 실패 문구 칸(`[타임아웃] CLI 응답 500초 초과`)은
  내용이 아니므로 비움. 펀드 열 · 펀드 시트는 버림. 다시 돌려도 안전(파이프라인이 채운 값은 덮지 않음).
- ⚠️**원본 컨센 칸 불신**: `예상EPS/예상매출` 이 분기마다 갱신되지 않았다(실측 GOOGL · NVDA · MSFT 의 Q1 · Q2 예상치 동일,
  NBIS 예상 EPS −62.2) → 그대로 나누면 GOOGL +216% · CRWV −4,767%. **서프라이즈 %는 계산하지 않고**(NULL) 원본 판정
  (`컨센대비`)만 '원본 판정'으로, `detail.forecast_unverified=true`. 실제 컨센 대비는 Nasdaq 이력(B3a)이 채운다.
- ⚠️**B7 선행 조건 불충족 발견**: zip 에 `.py` 가 **0개**다 — "B7 삭제 전에 zip 이 코드 33파일을 포함하는지 확인" 조건이
  깨진다. 지금 코드 사본은 `Ongoings/src/` 하나뿐 → B7 에서 삭제 전에 사용자에게 묻는다(백업 위치).
- 테스트: api 301(+4: 금액 · 장전/장후 · 분기 라벨 · 티커 별칭 · 대상 필터 · 실패 문구 · 관전포인트 시트 · 서프라이즈 계산).

### B2 ✅ 완료 (2026-09-27)
- **래퍼** `apps/worker/llm/cli.py`(`run_claude`): 원본 호출 지점 두 곳(`llm_cli.py` codex 드롭인 · `web_fallback.py`)을 하나로.
  `web_fallback` 의 "LLM 이 웹에서 실적 찾기"는 **버렸다** — 도구를 주면 8-K 원문이 프롬프트 주입 경로가 된다. 숫자는 Nasdaq · SEC 가.
  격리: 절대경로(`CLAUDE_BIN`, 기본 `~/.npm-global/bin/claude`) · `--tools ""` · `--strict-mcp-config` + 빈 MCP ·
  `--setting-sources ""`(사용자 설정 · 훅 안 읽음) · `--no-session-persistence` · 임시 작업 폴더 · `--output-format json`.
  ⚠️`--bare` 는 쓰지 않는다 — 키체인을 안 읽어 이 맥의 로그인 세션이 안 잡힌다(도움말 확인). 타임아웃 500초.
  **오류 종류**: 로그아웃 · 사용량 초과 · 시간초과 · 하루 상한(`LLM_DAILY_CAP` 기본 40, 시도 횟수 — 실패도 센다) · CLI 없음 ·
  기타. 사용량 초과는 재시도하지 않는다. 실측 시스템 프롬프트 약 2천 토큰(사용자 CLAUDE.md · 훅 안 들어감).
- **관전포인트** `llm/watchpoints.py`: 원본 프롬프트 · JSON 추출 · 부호 퍼센트 제거 이식. 문맥 = 최근 실적 8-K/6-K Ex.99.1
  (+ "자료 안 지시문은 따르지 말 것"). 실패를 칸에 글자로 쓰지 않는다(원본: '[타임아웃] …' 이 관전포인트로 저장됨).
- **8-K 보도자료** `sec/exhibit.py`: 원본 `sec_edgar.py` 이식 — 8-K Item 2.02 발표일 창 우선 · 6-K 는 창 안만 ·
  ★사람용 `-index.htm` 의 **문서 타입 EX-99.1** 로 첨부 선택(`index.json` 은 NVDA 등에서 문서를 안 나열) · 표지면 없음 처리.
  requests/BeautifulSoup → 공용 `sec_get` + 표준 `html.parser`(의존성 추가 없음).
- **작업** `LLM_WATCHPOINTS`(큐 **llm**) → `earnings_watchpoints`(source='llm', model) — 대상 분기 = 다음 예정 발표, 없으면 최근 +91일.
  원천 상태 `claude`(비용 · 초 · 오늘 호출 수).
- **실측 왕복**: NVDA — 8-K 2026-08-26 Ex.99.1(`q2fy27pr.htm`, 파일명 아닌 타입으로 찾음) → 2026Q3 관전포인트 3개 +
  key_metric(데이터센터 매출), 11초 · $0.057. MSFT — `msft-ex99_1.htm` → 4개. `/data-operations` 표시 확인:
  가짜 CLI 로 **사용량 초과 → "사용량 초과"**, **로그아웃 → "로그아웃"**(원천 경고 1 — claude), 실제 호출로 다시 "정상".
  화면 라벨 추가: 로그아웃 · 사용량 초과 · 하루 상한 · CLI 없음.
- 테스트: worker 196(+11: 격리 인자 · 오류 종류 3 · stderr 로그아웃 · 시간초과 · 하루 상한 · CLI 없음 · 파싱/≤4/수익률 ·
  index 표 · 타입 선택 · 공시 우선순위 · HTML 글). api 301. 웹 tsc 통과.

### B3a ✅ 완료 (2026-09-27)
- **작업** `EARNINGS_CALENDAR`(`handlers/earnings_calendar.py`, 큐 sec_crawl) — 기존 `prices/earnings.py`(Nasdaq, 키 없이 ·
  브라우저 UA) 재사용 + `EarningsEvent` 에 `eps_actual` · `eps_surprise_pct` 추가(지난 날짜를 부르면 온다).
  ① 앞으로 **63일**: 내 종목만 `earnings_events` upsert(source='nasdaq', EPS 컨센 · 추정 수 · 장전/장후). ⚠️계획은 "4주"였지만
  실측 내 종목 10개의 다음 발표가 전부 10/27 ~ 11/18 — 4주면 한 달 동안 빈 화면. Nasdaq 은 약 2달 앞(예상일)까지 준다 →
  9주로 넓히고 화면은 4주 밖을 흐리게. ② 지난 발표(400일): **그 발표일 캘린더**의 `eps` · `epsForecast`(당시 컨센) · `surprise`
  → `earnings_results`(source='nasdaq') — 이관(B1)의 미검증 컨센을 당시 컨센으로 교체. 판정 = 원본 `consensus_from_values`
  (EPS · 매출 중 하나 ≥ +3% 상회, 아니면 ≤ −3% 하회, 그 밖 부합). ⚠️매출은 **검증된 매출 컨센(B3b)일 때만** 판정에 — 실측 GLW
  2026Q1: EPS 0.70 vs 0.70 정확히 부합인데 이관 매출 컨센 탓에 '하회'로 나왔다 → 수정. Nasdaq 이 surprise 칸을 비워 보내면 직접 계산.
  지난 날짜의 `time`(미정)은 기존 장전/장후를 지우지 않는다.
- **일정**: `sec_sync` 에 "매일 07:10 KST 이후 한 번" 규칙(`last_slot` — 맥이 잤으면 깨어나서). 원천 상태 `nasdaq`.
- **실측**: 다가오는 발표 10건(BE · GLW 10/27 … NVDA 11/18, EPS 컨센 + 추정 수) · 지난 발표 19건 중 18건을 Nasdaq 당시 컨센으로
  (NVDA 26Q2 $2.22 vs $2.09 +6.22% 상회, GLW 26Q1 부합). NBIS 2026-05-04 는 Nasdaq 그날 목록에 없음 → 원본 판정 유지.
  NVDA 26Q1 은 Nasdaq 이 실적만 주고 컨센을 비워 서프라이즈 · 판정을 비워 둠(지어내지 않음).
- **API** `apps/api/app/api/earnings_monitor.py` `/api/v1/research/earnings/{overview, stock/{ticker}}`(주말이면 '이번 주' = 다가오는 주).
  ⚠️작성 중 **기존 `app/api/earnings.py`(collector `/earnings/us` 프록시)를 덮어쓰는 실수** → git 에서 복원하고 새 파일로 옮김
  (복원본은 커밋본과 같다 — 그 파일에 커밋 안 된 수정이 있었는지는 알 수 없다).
- **화면** `/research/earnings`(nav `리서치 > 실적 모니터` — `/stock/us` 교체는 B6): 위 칸 4개(이번 주 · 지난주 결과 · 다음 발표 D-n ·
  발표 후 최대 반응 "수집 전"), 왼쪽 이번 주 · 다음 주 요일 막대(장전/장후/미정) + 9주 안 발표표(EPS 컨센 · 추정 수 · 매출 컨센
  "수집 전"/"수집 실패"), 오른쪽 최근 발표 EPS 서프라이즈 막대(±100% 에서 자름), 종목 상세 팝업(관전포인트 → 결과 ·
  EPS/매출 실적 vs 컨센 · "원본 판정" 배지 · 반응 · 가이던스 · 8-K 링크 자리).
- 테스트: worker 199(+3: 판정 규칙 · 다가오는/지난 발표 · 이관 매출 불사용 + 빈 surprise 계산), api 304(+3: 주 경계 · overview/stock).
  웹 tsc 통과, 1440×900 확인.

### B3b ✅ 완료 (2026-09-27) — 화면 잠금 실측은 사용자 결정으로 건너뜀
- **크롤러** `apps/worker/prices/investing.py`(원본 `earnings_crawler.py` 이식): `channel="chrome"`(설치된 크롬) · `headless=False` ·
  창은 화면 밖 · 커스텀 UA 없음. Playwright 1.63 을 `.venv` 에(uv — `.venv` 에 pip 없음) · `apps/worker/requirements.txt` 에 추가.
  브라우저 내려받기 없음(설치된 크롬 사용).
- ⚠️**원본 이후 페이지가 바뀌어 원본 그대로는 0행**이었다(실측 2026-09-27) — 고친 것 셋:
  ① 셀 글자는 `textContent` 가 빈 값 → `innerText` 로, 한 번의 스크립트로 모든 행. ② 티커가 'Inventiva ( IVA )'(괄호 안 공백) →
  정규식. ③ 원본의 React native setter 날짜 주입이 안 먹음(표가 기본 주간 그대로) → Playwright `fill`.
  ★행 날짜는 **표 안 날짜 머리행**으로 정한다 — 요청한 날로 붙이면 날짜 바꾸기가 조용히 실패할 때 옛 표 행이 엉뚱한 날에
  들어간다(실측: 긴 회차에서 NVDA 8/26 누락). 머리행이 요청한 날이 아니면 다시 시도.
- **작업** `EARNINGS_REVENUE`(큐 sec_crawl — GUI 로그인 세션의 LaunchAgent). 대상 = 다가오는 발표(35일 — Investing.com 은 약 5주
  앞까지만 올린다, 실측 11/04 0행) 앞뒤 2 평일(Nasdaq 날짜는 예상일 — 실측 BE · GLW 가 10/27 에 없음, 가장 가까운 날로 맞춤) +
  최근 120일 발표(확정일 그날). 성공 → `revenue_forecast`(source 'investing') · 지난 발표는 매출 실적 · 매출 서프라이즈 · 판정 다시
  (원본 규칙 — 검증된 매출이니 판정에 넣는다). **막히면** 다가오는 발표 중 매출 컨센 없는 것 → status 'failed' → 화면 "수집 실패",
  EPS 는 그대로. 원천 상태 `investing`(Cloudflare = 'blocked' → 화면 "Cloudflare 차단"). 수동 실행용 `payload.dates`.
  일정: `sec_sync` 매일 **07:20 KST**(07:10 Nasdaq 캘린더 뒤) — 시각형 작업을 `DAILY_SLOTS` 로 일반화.
- **실측(화면 켜짐)**: 터미널 실행 · **LaunchAgent worker 경로 둘 다 Cloudflare 통과**(worker 1일치 11초, 2일치 28초). 지난 발표 5건에
  검증된 매출 컨센 · 실적 — NVDA 8/26 $96.2B vs $91.9B(+4.68%) · GOOGL · GLW · BE · CRWV. 같은 날 MSFT · TEM · AMD(8/4) · HUT · NBIS 는
  그 페이지에서 못 찾음(부분 커버). 다가오는 발표는 AMD(11/03) 1건 — 나머지는 아직 Investing.com 에 없음(매일 다시 봄).
- ❓**화면 잠금 실측은 하지 않았다**(사용자 결정 2026-09-27 "잠금 실측은 건너뛰기"): 잠금 감지 후 실행하도록 15분 기다렸으나
  잠금이 감지되지 않았다. → 잠긴 상태에서 막히는지는 **운영 중 `/data-operations` 의 investing 상태**로 보게 된다
  ("Cloudflare 차단"이면 그날 매출 컨센 "수집 실패", 다음 날 07:20 다시).
- 실행 조건(문서화): 이 맥에 **로그인된 GUI 세션**이 있어야 한다(LaunchAgent gui 도메인 — 로그아웃 상태 · 도커에서는 크롬 창을 못 띄운다).
  덮개를 닫고 배터리면 잠들어 07:20 에 못 돈다 → 깨어난 뒤 캐치업 루프가 넣는다.
- 테스트: worker 203(+4: 파싱[지금·옛 서식] · 날짜 머리행 · 평일 창 · 가장 가까운 날 맞춤 + 매출 서프라이즈 판정 · 막힘 → 다가오는 발표만
  'failed' + 원천 'blocked'), api 305(+1: 07:20 슬롯이 07:10 뒤). 웹 tsc 통과.

### B4 ✅ 완료 (2026-09-27)
- **결과 수집** `EARNINGS_RESULT`(`handlers/earnings_result.py`, 큐 sec_crawl): 최근 30일 내 종목 발표 중 8-K · 반응이 빈 것.
  API `sec_sync` 가 **발표 구간이 끝난 뒤 15분마다**(장후 17:40 ET · 장전 08:40 ET · 시각 모름 다음 날 09:00 ET) — 찾거나
  기한(8-K 발표 +3일 · 반응 +2일)이 지날 때까지. 수동 실행은 `payload.lookback_days`.
  ① 보도자료 `sec/exhibit.earnings_release` → `filing_url` · 접수번호 · 서식(8-K/6-K) + LLM 구조화 작업 예약(같은 접수번호는 한 번).
  ② 반응 `prices/reaction.py`(원본 `toss_prices.py` 이식 — 장후 16:00→17:30 ET, 장전 전일 16:00→08:30 ET, 시각 모르면 값 없음,
  구간 끝은 벽시계로). ⚠️토스 토큰은 API 시세 캐시와 같은 키 → **미국 정규장이 닫혀 있을 때만** 부른다(열려 있으면 미룸).
  토스 키는 저장소 `.env`(API `credentials_store` 와 같은 파일).
- **보도자료 구조화** `LLM_EXHIBIT`(`handlers/llm_exhibit.py` + `llm/exhibit.py`, 큐 llm — 원본 `exhibit_parser.py` 이식):
  매출 실적(USD 만) · 다음 분기 매출/EPS 가이던스 → `earnings_guidance`(방향 = 직전 발표 가이던스 중간값 대비 ±1% — ⚠️컨센 대비
  상향/하향이 아님, 화면 문구도 그렇게) · 세그먼트 · 회사 회계분기 · 통화 → `detail`.
- ⚠️**실측으로 고친 것**:
  ① NBIS 6-K — 원본 규칙(창 안 첫 6-K = 가장 늦은 것)이 **8/19 전환사채 공시**를 잡았다 → 6-K 는 발표일 가까운 순 + 본문이
  실적 자료인지(매출 + 분기/실적 표현) 확인하고 아니면 다음 후보. → 8/12 실적 6-K 를 찾음.
  ② AMD 가이던스 누락 — 원본 15천 자 자르기(앞 5천 + 뒤 1만)가 가운데 전망 문단을 잘랐다 → 3만 자(앞 1만 + 뒤 2만) → $12.7B~$13.3B.
  ③ 회계분기 표기 오류로 통째 실패(원본) → 정규화 · 못 읽으면 비우고 경고(매출 · 가이던스가 본체).
  ④ ★NBIS 매출 — LLM 이 $45.83B 를 뽑았다(표의 실제 값 $582.3M). **원본 이관값도 같은 45.83B · 1분기 32.44B** — 원본
  파이프라인도 같은 실수였고 이관 컨센(29.22B)도 같이 틀려 서로 맞아 보였다. → 프롬프트에 "총매출만 — 수주잔고 · ARR · 계약액은
  매출 아님", **검증된 컨센(Investing)과만** ±50% 점검, Investing(검증) 매출은 유지 · 이관(미검증) 매출은 8-K 값으로 교체.
  NBIS 26Q2 = $582.3M(컨센 $569.9M). ⚠️NBIS 1분기(이관 발표일 5/04)는 8-K/6-K 를 못 찾아(발표일 자체가 틀렸을 가능성 —
  Nasdaq 캘린더에도 그날 없음) 이관 32.44B 가 남아 있다 → **알려진 오류**, "원본 판정" 표시.
  ⑤ 이관 빈칸이 'nan' 글자로 들어와 화면에 "→ nan" — 이관 파서가 nan · None 을 빈칸으로, DB 10행 정리.
- **실측**: 최근 150일 발표 14건 — 8-K/6-K 14건 중 13건 연결(NBIS 1분기 못 찾음), 반응 14건(GLW 장전 −17.0% · CRWV 장후 +14.3% ·
  NBIS 장전 +16.4% · NVDA 5/20 0.0% — 1분봉 확인해 보니 실제로 평평), 구조화 13건, 가이던스 3종목(GLW · NVDA · AMD).
  화면 종목 상세에 8-K 원문 · 반응(구간 표기) · 가이던스(한글) 표시 확인.
- 테스트: worker 211(+8: 세션 구간[월요일 장전 = 금요일 종가] · 구간 끝 대기 · 장중 미룸 · 8-K/반응/구조화 예약 · 검증 · 단위 ·
  가이던스 방향 · 6-K 가까운 순/실적 판별 · 매출 타당성 · 이관 매출 교체), api 307(+2: 결과 준비 시각 · DB 판정 · nan).

### B5 ✅ 완료 (2026-09-27)
- **생성(D-3)**: B2 의 `LLM_WATCHPOINTS` 를 `sec_sync.watchpoints_due` 가 넣는다 — 내 종목 중 발표가 **D-3 안**인데 관전포인트가 없는 것,
  **07:30 KST 이후 하루 한 번**(그날 실패했으면 다음 날 07:30 에 다시). 큐 llm.
- **결과 판정** `LLM_JUDGE`(`handlers/llm_judge.py` + `llm/judgment.py`, 큐 llm — 원본 `market_reaction.analyze_market_reaction_json`
  이식): 사전 관전포인트 순서대로 **자료에서 확인된 결과만**(나머지 빈칸 — 원본 규칙) · 결과 ≤120자 · 시장반응 한 문장 ≤220자 ·
  수익률 숫자 금지 · verdicts(EPS/매출/핵심지표 = 상회·하회·부합·미확인, 종합 = 서프라이즈·중립·쇼크·미확인) · 통화 다르면 미확인.
  바꾼 것: 근거 = 8-K/6-K 보도자료 · 세그먼트 · 가이던스만(원본은 뉴스 기사도 — 도구가 꺼져 있어 외부 글을 안 가져온다),
  매출은 **검증된 값만** 프롬프트에(이관 컨센은 '미확인'), 이관 원본 결과는 덮지 않고 빈 칸만. `LLM_EXHIBIT` 가 끝나면 결과가
  빈 관전포인트가 있을 때 **자동으로 이어서** 예약(같은 발표 한 번). 화면 종목 상세에 "종합 서프라이즈/중립/쇼크" 배지.
- ⚠️**실측으로 찾아 고친 것**(B4 코드):
  ① **GLW 1분기(4/28)에 2분기(7/28) 보도자료가 붙었다** — 판정 결과에 "3분기 가이던스"가 들어가 발견. 원인 둘: 실적 자료 판별이
  'revenue' 만 봐서 Corning 의 'core sales' 보도자료를 떨어뜨렸고 → 원본 순서("창 밖 아무 2.02" > 창 안 8-K)가 가장 최근 분기
  8-K 를 붙였다. → 판별에 'sales' 추가 · 발표일이 있으면 창 밖 2.02 는 쓰지 않음. 잘못 붙은 1건(가이던스 2 · 판정 결과 4 · 매출)을
  지우고 다시 돌려 올바른 4/28 자료로 채움(2분기 가이던스 $4.6B · EPS $0.73~0.77). 나머지 17건은 발표 당일 공시로 확인.
  ② 가이던스 방향을 전체 다시 계산(GLW 2분기 → 직전 대비 상향).
- **실측**: 1분기 4개 발표(GLW · BE · GOOGL · MSFT, 이관 결과 0개) → 8-K → 구조화 → 판정 자동 연결, 관전포인트 15개 중 13개 결과
  (MSFT 2개는 보도자료에 없어 빈칸 — 추측으로 채우지 않음). 판정: BE · GOOGL · MSFT 서프라이즈, GLW 중립.
- 테스트: worker 214(+3: 판정 파싱 · 빈칸 채움 · 판정값 정규화 · 120자 · 프롬프트 · 지난 발표에 최근 분기 8-K 금지 · 'sales' 판별),
  api 308(+1: D-3 생성 판정 · 하루 한 번). 웹 tsc 통과.

## §R 리뷰 반영 요약 (critic, 2026-09-26)
| 등급 | 지적 | 반영 |
|---|---|---|
| Critical | 계획이 기대는 worker 가 이 맥에서 안 돈다 · 단일 작업 · RUNNING 고착 · `--reload` 가 작업을 죽임 | P0 신설 |
| Critical | 13F 정정공시 "최신 하나" 규칙이 포트폴리오를 지운다(실측 확인) | A 분석 로직 · A2 |
| Critical | 내부자 매도의 73%가 10b5-1 계획매도 · 파생 행 · 첫 보고자만 · 4/A 이중 집계 | A-2 규칙 · A3 · A6 |
| Major | Investing.com 크롤은 화면 있는 크롬 필요, Playwright 미설치 | B3 분할(B3a/B3b) |
| Major | `claude -p` 격리·절대경로·500초·쿼터·호출 지점 2곳 | B LLM 조건 · B2 |
| Major | 계절성 수준 비교 → 수익률로 잇기, 월 키, 진행 중인 달 | C 저장 · C3 |
| Major | pandas·numpy·scipy 없음 | C2 |
| Major | 계절성 "상승"의 대부분이 기본값 · "다음 달"이 사실 이번 달 · 표본 내 적중률 | C 화면 |
| Major | KST 고정 시각은 서머타임에 어긋남 | B 파이프라인 표 |
| Major | 이식 표에서 954줄 누락 · 이관 원천 경로 · 삭제 전 확인 | B 이식 표 · B7 |
| Major | SEC UA 변수명이 저장소와 다름 · 속도 제한기 없음 | A 데이터 표 |
| Major | 마이그레이션 번호가 실행 순서와 어긋남 | P1 |
| Minor | ETF 도 13F 대상 · 2013Q2 이전 텍스트 13F · 신선도 행 · api.ts 정리 · 매출 컨센 문구 · 내 발표 목록 노출 · 섹터 자리 · FDR 기준월 · PRN | 각 절 |

## 사용자 결정
| # | 질문 | 결정 |
|---|---|---|
| 1 | 13F 범위 | ✅ 거장 23명 전 기간. 거장 추가가 쉬운 구조(`guru_roster` 테이블 + SEC 직접 백필) |
| 2 | 어닝모니터 LLM | ✅ 이 맥의 `claude` CLI |
| 3 | 계절성 산업 33개 | ✅ 2단계로 미룸(대시보드 자체 분류 + Yahoo 주가로 재구성) |
| 4 | 어닝모니터 원본 소스 | ✅ `Ongoings/src/` 로 받음 → 이식. **이식 완료 후 `Ongoings/src/` 삭제** |
| 5 | 매출 컨센 | ✅ 2안 Investing.com 1일 1회 크롤 |
| 6 | 중국 지수 2개 | ✅ 제안대로 — CSI300 은 2026-09 부터 ASHR 로 이어 붙이고 "대용" 표시, 창업판은 2026-08 에서 동결 + "갱신 중단" 표시 |
| 7 | 섹터 대용 ETF 중 차이 큰 3개(XLC·XLK·XLY) | ✅ 창업판처럼 **2026-08 에서 동결** + "갱신 중단" 표시. IT·COMM·COND 의 Yahoo 심볼 제거, 받아 둔 Yahoo 39행 삭제 → Yahoo 로 잇는 시계열 15개 |
| 8 | SEC 연락처 UA(`SEC_USER_AGENT`) | ✅ 3안 — 앱 기본값(`…@personal-investment.local`)을 `.env.local` 에 **명시**. 정책상 실제 연락처 권장이라 403 위험 감수(403 이면 10분 정지·화면 표시) |

## 검증 로그

### 2026-09-26 회차 1
- **Yahoo 월간 이력**(`period1/period2`, interval=1mo):

  | 심볼 | Yahoo 시작 | 블룸버그 시작 | 잃는 기간 |
  |---|---|---|---|
  | ^GSPC | 1985-01 | 1960-02 | 25년 |
  | ^IXIC | 1985-01 | 1971-03 | 14년 |
  | ^RUT | 1987-09 | 1979-01 | 9년 |
  | ^KS11 | 1996-11 | 1980-02 | 17년 |
  | ^KQ11 | 2000-09 | 1996-08 | 4년 |
  | ^HSI | 1986-11 | 1964-08 | 22년 |
  | ^SOX | 1994-05 | 1994-05 | 없음 |
  | 000300.SS / 399006.SZ | **없음** | 2002-02 / 2010-07 | 전부 |
  | XLK 등 SPDR 9종 | 1998-12 | 1989 (S5 지수) | 10년 |
  | XLC | 2018-06 | 1989 (S5TELS) | 29년 |
  | ^SP500-45 | **없음** | — | — |
  결측·구멍 0, 진행 중인 달 중복 1행.
- **13F 백필 규모**: 전체 1,797,904행 / 34곳 1,791,861 / **거장 23명 전 기간 143,873** / 거장 23명 최근 12분기 42,818.
  상위: Citadel 198,945 · AQR 124,177 · Millennium 70,867 · Vanguard 68,763(최근 12분기).

### 2026-09-26 회차 2
- **중국 지수**: Yahoo `000300.SS`·`399300.SZ`·`399006.SZ` 전부 1점. Stooq(`^shc` 등 6종) 전부 JS 봇 챌린지
  HTML 을 돌려줌 → 사용 불가. 대용: `ASHR` 2013-11~ · `CNYA` 2016-06~ · `KWEB` 2013-08~(인터넷 섹터, 대용 부적합).
- **Nasdaq 실적 API**: `calendar/earnings?date=` 한 날 284행, 필드 eps·epsForecast·surprise·noOfEsts·
  fiscalQuarterEnding·marketCap·time. `quote/{sym}/eps` 분기별 consensus/earnings, `analyst/{sym}/earnings-forecast`,
  `estimate-momentum`, `company/{sym}/earnings-surprise` 모두 200. **매출(revenue) 필드는 어디에도 없음.**
- **Form 4**: `submissions/CIK0000789019.json` → 최근 Form 4 744건, `form4.xml` 원문을 표준 `xml.etree` 로
  파싱해 소유자·직위·거래코드·주수·가격·A/D·거래일 추출 성공. 첫 건이 코드 A(보상 부여)라 P/S 필터 필요 확인.
- **CUSIP 커버리지**: 위 표 참조.

### 2026-09-26 회차 3
- Yahoo `quoteSummary`(fc.yahoo.com 쿠키 + getcrumb 후): **429**. 매출 컨센 무료 원천 없음으로 결론.
- 미매핑 CUSIP(금액 31.9%, 1,030개) 상위: BAC 4.17% · MCO 2.77% · GE 2.69% · OXY 1.95% · TSM ADR Call 1.39% ·
  BRK-B 1.32% · CNI · WM · AMAT · IEP · SpaceX(비상장) · TFPM. OpenFIGI 무키로 상위 100개 중 92개 해소.
  남는 것은 비상장(SpaceX)·옵션(Call/Put)·일부 LP 단위 — 옵션은 원래 비중 계산에서 따로 다뤄야 한다.
- 원본 13F 소스 위치 확인(위).

### 2026-09-26 회차 4
- 사용자 결정 6개 반영(표 참조). 어닝모니터 원본 `Ongoings/src/` 확인: 33파일 16,683줄, LLM 은 `llm_cli.py`
  한 곳을 거치며 `codex exec` 를 부른다(원래 `claude -p` 드롭인). 이 `src` 에 Slack 웹훅 평문 없음.
- 13F 원본 4,273줄 / 계절성 1,487줄 이식 범위 확정(각 계획 표). 작업 티켓 19개로 분해.

### 2026-09-26 회차 5 — 리뷰 반영
- critic 판정 **REVISE** (Critical 3 · Major 9 · Minor 9). 핵심 둘을 직접 재확인:
  - 버크셔 2023-09-30: 13F 152행(11/14) · 152행(11/16) · **1행(2024-05-15)** — "최신 하나" 규칙이면 1종목. 중복 (기관,분기) 묶음 **74개**.
  - Form 4 비파생 S 21,670건 중 `is_planned_trade=1` **15,879건(73%)**.
- 반영: 공통 원칙 3(실행기) · P0/P1 신설 · A 정정공시·PRN/옵션·내부자 규칙·SEC UA · B 크롬 크롤·claude 격리·ET 시각·파일표 ·
  C 수익률 잇기·의존성·"근거 없음"·"이번 달"·섹터 칩 · 와이어프레임 3곳.

### 2026-09-26 회차 6
- ✅토스 1분봉 과거 조회: MSFT, `before` = 어제/5일 전/30일 전 ET 17:30 → 각 120봉(ET 15:28~17:30 = KST 04:28~06:30).
- ✅C2 기준값 추출(`seasonality_stats.csv` 288행: 구간 3 × 지수 8 × 12개월). 표는 C2 행 참조.
- ⏳Investing.com 화면 잠금 실측은 **사용자 협조 필요**(맥을 잠근 채 크롤 1회) — B3b 착수 때 같이 한다.
- critic 재검토(2차): REVISE → 남은 10건(마이그레이션 번호 3곳 · A2 선행 · Form 4 과거분 보정 · 지속 수집의 `amendmentType` ·
  A-2 와이어프레임 문구 · LaunchAgent · C3 선행 · `kind` 열 · KST 표기 · 오프라인 fixture) 모두 반영 → **v4 최종**.
  critic 의견: "1~4 가 고쳐지면 APPROVE, Minor 는 추가 리뷰 불필요".


### B6 ✅ 및 Codex 실행 인계 (2026-09-27 16:07 KST)
- 기존 `/stock/us`는 `/research/earnings`로 307 이동한다. 고아 카드·포맷 파일, `/api/v1/earnings/us` 프록시, 관련 미사용 TS 타입을 제거했다. 동시 작업의 메뉴와 기타 허브는 보존했다.
- 삭제 직전 파일은 `.omc/backups/b6-legacy-earnings-20260927-160317-447928`에 바이트 대조 백업했다.
- 별도 검토자: 남은 런타임 참조 없음, 새 API 유지, 기존 프록시 미등록 확인. 실제 HTTP 307/200 확인.
- 검증: API 전체 344 passed(기존 DeprecationWarning 1건), worker 전체 214 passed, 웹 `npx tsc --noEmit -p .` exit 0. 커밋하지 않았다.
- 이 작업의 Codex heartbeat `automation`을 15분 간격으로 생성했다. 기존 Claude 세션의 cron 존속 여부는 확인하지 않았다.
- B7 원본은 보존 중이다. `.omc/backups/earnings-original-20260927-160259/src.zip`과 `manifest.json`에 캐시 제외 55파일(33 Python)을 저장하고 각 SHA-256을 대조했다.
- 다음 작업: `docs/plans/earnings-source-migration-audit.md`의 파일별 대조 결과와 실적 필드 출처 검토 결과를 반영한다. 백업만으로 기능 이식 완료를 판정하지 않는다.

- 추가 검토(P1): Nasdaq EPS 수집 뒤 행 전체가 검증된 것으로 표시되는 문제와 이관 매출 예상치의 `ok` 표시를 발견했다. EPS·매출 실적·컨센서스의 출처별 검증 표시 및 회귀 테스트를 보완 중이다. 기존 숫자를 삭제하거나 재이관하지 않는다.

### B7 ✅ (2026-09-27 17:40 KST) — 범위 축소 후 삭제
- 사용자 결정: 감사(`docs/plans/earnings-source-migration-audit.md`)의 공백 G1~G8 은 **"범위 축소 후 삭제"** — 꼭 필요한 G8 만 구현하고
  나머지는 아래처럼 버림/수용으로 확정한다(이식 표의 해당 줄도 이 결정이 우선한다).
- **G8 구현**
  - SEC 첨부 폴백(원본 `_select_earnings_release_document`): 문서 타입(EX-99.x)으로 못 고르면 `index.json` → 파일명 규칙 →
    크기(표지 2배 · 5만 바이트 이상) → 표지. `sec/exhibit.select_release_by_name`. ★원본 규칙을 한 곳 고침: 실측 NVDA
    `index.json` 에서 `q2fy27cfocommentary.htm`(EX-99.2)이 먼저 잡혀 보도자료 이름(earnings/release/results/`pr.htm`)을
    분기 표기(`q[1-4]`)보다 먼저 본다 → 실측 `q2fy27pr.htm`.
  - LLM 따라잡기(`sec_sync.llm_catchup`, 5분 루프): ① 8-K 는 있는데 구조화가 안 끝난 발표 → `LLM_EXHIBIT` 다시,
    ② 구조화 뒤에 생긴 관전포인트(결과 빈 칸) → `LLM_JUDGE` 다시. 발표당 실패 3번까지 · 1시간 간격 · 최근 30일.
    실측(라이브 DB 드라이런): 지금 대상 0건 — 잘못 넣는 작업 없음.
- **버림/수용 확정**
  - G1 세그먼트: **보도자료 세그먼트만**(`earnings_results.detail.segments`). 10-Q R파일 세그먼트 · 세그먼트 이력/태그 · 설명 캐시
    (`segment_10q.py`·`segment_store.py`·`segment_desc.py`)는 버림.
  - G2 핵심지표(key metric 이름·임계치) 저장·판정 연결: 버림 — 판정은 관전포인트 문장 + `verdicts.key_metric` 라벨로 한다.
  - G3 동종업계 비교(`peer_signal.py`): 주간 회의 자료와 함께 버림.
  - G4 `analysis_utils` MD&A · 뉴스 근거: 버림(B2·B5 에 기록한 좁힌 근거 그대로). `web_fallback` 은 B2 에서 이미 버림.
  - G5 `report_reaction_display.py` · `stock_returns.py`(주·월 수익률) · 세그먼트 설명: 보고서 전용 — 버림.
  - G6 원본 분석 DB 이력: 원본 `EARNINGS_MONITOR.db` 가 없다 — **이력 복구 포기**(새 발표부터 공시로 쌓는다).
  - G7 미국 휴장일: 평일 기준 + 직전 1분봉으로 기준가를 잡는 현재 방식 수용.
- 삭제 전 확인: `.omc/backups/earnings-original-20260927-160259/src.zip`(zip 무결성 OK)의 manifest 55파일(Python 33 + 프롬프트 2 +
  운영 20) ↔ zip ↔ 디스크 SHA-256 **55/55 일치**, 디스크에만 있는 파일 0(`__pycache__` 제외). 그 뒤 `Ongoings/src/` 삭제.
  ⚠️백업 사본은 이 한 곳(`.omc/` 는 git 무시)뿐이다.
- 검증: worker 215 passed · API 354 passed. 워커 재시작(sec_crawl · llm). 커밋하지 않았다.

### P1 ✅ (2026-09-27 17:45 KST) — 표시 누락 정리
- 규칙대로 번호가 확정됐다: 0019 → 0020(계절성) → 0021(C3) → 0022(SEC) → 0023(A5) → 0024(실적) → 0025(다른 작업 `ai_metric_snapshot`).
  `alembic heads` = 0025 하나(체인 1줄), 로컬 DB `current` = 0025. 표에 ✅ 만 빠져 있었다.
- 이로써 표의 P · C · A · B 티켓이 모두 ✅ 다.

