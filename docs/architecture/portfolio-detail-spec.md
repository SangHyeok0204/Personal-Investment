# 포트폴리오 상세 페이지 스펙 (BINDING — round 3)

`contract.md`(round 1) + `contract-kiwoom.md`(round 2)를 확장한다. 이 문서가 이번 라운드의 계약이다.
사용자 결정사항(2026-07-12) 반영. UI 방향은 `reference/index.png`("Invest AI") 유지.

## 0. 확정된 결정 (재논의 금지)

| 항목 | 결정 |
|---|---|
| 자산군 분류 | **A. 종목별 수동 지정** — 키움이 자산군을 주지 않으므로 우리가 관리. 아래 §2 |
| 도넛 | **5분류: 주식 / 채권 / 파생 / 기타 / 현금**. 총매입금액은 도넛에 넣지 않음(부분-전체 관계 아님) → 평가손익 옆 별도 |
| 손익 색상 | 현행 유지 — **상승 초록 / 하락 빨강** (미국식) |
| 비중 기준 | **총자산 대비**(현금 포함). 도넛과 기준 일치 |
| 테이블 컬럼 | **평균매입가 → "평단가"** rename, **매입금액 유지**, **국가 컬럼 삭제** |
| 데이터 상태 박스 | 삭제 → 오류 정보는 Top bar 상태등으로 흡수 |
| 상세 페이지 범위 | 전체 보유 종목 (메인 대시보드의 `EXCLUDED_DASHBOARD_TICKERS` 필터 **미적용**) |

## 1. Top bar — 페이지별 동적 bar

**요구**: 사이드바처럼 고정된 전역 bar가 아니라, **선택한 메뉴에 따라 내용이 달라지는** bar. UI 골격(높이·테두리·우측 아이콘)은 공통.

**구조** (kw-web):
```
components/layout/topbar.tsx     공통 셸: sticky top-0, h-16, border-b, bg-white
                                 props: title, subtitle?, status?, actions?
app/layout.tsx                   기존 topbar 마크업 제거 → <main>{children}</main> 만
app/page.tsx                     <Topbar title="메인 대시보드" ... />
app/portfolio/page.tsx           <Topbar title="포트폴리오 상세" status={<SyncStatusLight/>} actions={<SyncButton/>} />
app/data-operations/page.tsx     <Topbar title="데이터 작업" />
app/settings/page.tsx            <Topbar title="설정" />
```
우측 글로벌 아이콘(검색·알림·도움말·프로필)은 셸이 항상 렌더. 페이지는 좌측 title/status와 actions만 채운다.

**동기화 상태등** (`SyncStatusLight`):
| 조건 | 표시 |
|---|---|
| 최근 SYNC 작업 SUCCESS + connection.status=CONNECTED | 🟢 초록 점 + "연결됨" + "마지막 동기화 N분 전" |
| 최근 SYNC FAILED 또는 connection.status=ERROR | 🔴 빨강 점 + "오류" + `last_error` 요약(한 줄, 말줄임) |
| 진행 중(PENDING/RUNNING) | 🔵 파란 점(점멸) + "동기화 중" |
| NEVER_SYNCED | ⚪ 회색 점 + "동기화 이력 없음" |
데이터 소스는 `GET /api/v1/portfolio/overview`의 `sync_status` + `connection`. 5초 폴링.

## 2. 자산군 분류 (asset_type) — 수동 지정

**값**: `STOCK`(주식) · `BOND`(채권) · `DERIVATIVE`(파생) · `OTHER`(기타). 현금은 종목이 아니므로 `account_balances`에서 별도로 온다.

**핵심 규칙**:
- **워커는 asset_type을 절대 덮어쓰지 않는다.** 현재 워커는 upsert 때 `'STOCK'`을 하드코딩하는데, 이러면 사용자가 지정한 분류가 다음 동기화에 날아간다. `ON CONFLICT DO UPDATE`에서 asset_type을 **제외**할 것. 신규 종목만 기본값 `STOCK`으로 INSERT.
- 사용자는 UI에서 종목별로 분류를 바꾼다 → `PATCH /api/v1/assets/{asset_id}` `{"asset_type": "BOND"}` → 200 + 갱신된 asset.
- 마이그레이션 `0003_asset_classification`: 현재 12종목의 분류를 **idempotent UPDATE**로 seed (티커 기준, 존재할 때만).

**seed 분류** (근거: 실제 상품 성격):
| 티커 | 종목 | 분류 |
|---|---|---|
| SGOV | 미국 초단기 국채 ETF | **BOND** |
| TSL | 테슬라 1.25배 레버리지 ETF | **DERIVATIVE** |
| GLD | 금 SPDR ETF | **OTHER** (원자재) |
| XLB | S&P500 원자재 섹터 SPDR ETF | STOCK (원자재 *기업 주식* ETF) |
| SCHD | 미국 배당주 슈왑 ETF | STOCK |
| NVDA, MSFT, GOOGL, GLW, SKHYV | 개별주 | STOCK |
| 000660, 388720 | 국내 개별주 | STOCK |

이 분류 기준 도넛(현재 데이터): 주식 21.9M(48.4%) · 채권 10.6M(23.3%) · 파생 4.1M(9.0%) · 기타 2.8M(6.2%) · 현금 5.9M(13.0%) = 45.3M.

## 3. API 변경 (kw-api, `apps/api/**` + `database/migrations/versions/0003_*.py`)

- **마이그레이션 0003**: §2의 seed UPDATE. 스키마 변경 없음(asset_type 컬럼은 이미 존재).
- `PositionOut`에 **`asset_type`** 추가(패스스루).
- `GET /api/v1/portfolio/overview` 응답에 **`asset_class_breakdown`** 추가:
  ```json
  [{"asset_class":"STOCK","value_krw":21933000.0,"weight_pct":48.4,"position_count":9},
   {"asset_class":"BOND", ...}, {"asset_class":"DERIVATIVE", ...},
   {"asset_class":"OTHER", ...}, {"asset_class":"CASH","value_krw":5900853.0,"weight_pct":13.0,"position_count":null}]
  ```
  - 값 없는 클래스도 **0으로 포함**(도넛 범례가 항상 5칸). 순서 고정: STOCK, BOND, DERIVATIVE, OTHER, CASH.
  - `value_krw`: 종목은 Σ `current_positions.market_value_krw` GROUP BY `assets.asset_type`; CASH는 `summary.cash_value_krw`.
  - `weight_pct` = value ÷ `summary.total_assets_krw` × 100 (총자산 0이면 0).
- **`PATCH /api/v1/assets/{asset_id}`** body `{"asset_type": "STOCK|BOND|DERIVATIVE|OTHER"}` → 200 AssetOut. 잘못된 값 → 400 VALIDATION_ERROR. 없는 id → 404 ASSET_NOT_FOUND.
- 기존 §6(round 2) 응답 형태는 그대로 유지(비중은 web에서 총자산 기준으로 계산하므로 API 변경 없음 — 단 `positions[]`에 `market_value_krw`가 이미 있어 충분).
- 테스트: asset_class_breakdown(5칸 고정·0 포함·CASH 합산), PATCH 성공/400/404, 마이그레이션 seed 후 분류 반영.

## 4. Worker 변경 (kw-worker, `apps/worker/**`)

- `assets` upsert의 `ON CONFLICT DO UPDATE` 대상에서 **`asset_type` 제외** (사용자 분류 보존). 신규 INSERT 시에만 `'STOCK'`.
- 테스트: 사용자가 BOND로 바꾼 종목이 재동기화 후에도 BOND로 남는지 회귀 락(이게 이번 라운드의 핵심 함정 — 조용히 덮어쓰면 도넛이 다음 동기화에 원상복구됨).
- ⚠️ **`ON CONFLICT DO NOTHING`으로 바꾸지 말 것.** asset_type을 "보존"하는 것처럼 보이지만 (a) 키움에서 오는 `name`/`currency` 갱신이 멈추고, (b) 충돌 시 `RETURNING id`가 **행을 반환하지 않아** 기존 종목의 포지션 upsert가 전부 크래시한다. 반드시 DO UPDATE의 SET 목록에서 `asset_type` **한 컬럼만** 제외할 것.
- 테스트 단언 주의: `name`·`currency`는 갱신되는지 확인할 수 있지만 **`market`은 불가** — 충돌 키 `(country, market, ticker)`의 일부라 market이 다르면 애초에 다른 행이다. `name` 갱신 단언이 "한 컬럼만 얼렸다"(정답)와 "DO NOTHING"(오답)을 가르는 지점.

## 5. Web 변경 (kw-web, `apps/web/**`)

### 5.1 `/portfolio` 레이아웃
```
[Topbar: 포트폴리오 상세 · 🟢 연결됨 · 마지막 동기화 2분 전 · (키움 계좌 동기화)]

┌ 자산 배분 (도넛 5분류) ┬ 총자산 ┬ 보유종목수 / 평가손익 / 수익률 / 총매입금액 ┐
└────────────────────────┴────────┴──────────────────────────────────────────────┘
┌ 예수금 (KRW + USD 한 박스) ────────────────────────────────────────────────────┐
└────────────────────────────────────────────────────────────────────────────────┘
┌ 보유 종목 (정렬 가능 테이블) ──────────────────────────────────────────────────┐
└────────────────────────────────────────────────────────────────────────────────┘
```
- **도넛**: 5분할(주식·채권·파생·기타·현금), 중앙에 총자산. 0%인 클래스는 범례에만 표시(슬라이스 없음). CSS conic-gradient 재사용(메인 대시보드와 동일 기법, 새 차트 라이브러리 금지).
- **총자산**: **백만원 단위** 표시 (예: `45.3M` 또는 `4,528만원` — 기존 포맷 헬퍼와 일관되게, `formatKrwCompact` 신설 권장).
- **보유종목수 / 평가손익(+수익률) / 총매입금액**: 도넛 옆 별도 카드. 손익 색상 = 상승 초록/하락 빨강.
- **예수금 박스 하나**: `KRW -1,027원` + `USD $3,976.74 (₩5,901,880 · 환율 1,484.10)`. 환율은 `cash_balances[].exchange_rate`. FX 임의 계산 금지 — `cash_krw`를 그대로 표시.

### 5.2 보유종목 테이블
- 컬럼(13): ~~국가~~ 삭제 / 시장 · 종목명 · 티커 · **자산군** · 통화 · 보유수량 · **평단가**(← 평균매입가) · 현재가 · 매입금액 · 평가금액 · 원화환산 평가금액 · 평가손익 · 수익률 · 비중
  - **자산군 컬럼**은 인라인 `<select>`(주식/채권/파생/기타) → 변경 시 `PATCH /api/v1/assets/{id}` 호출 → 성공 시 overview 쿼리 invalidate(도넛 즉시 갱신). 이게 §0의 "수동 지정" UI다.
- **정렬**: 매입금액 · 평가금액 · 평가손익 · 수익률 헤더 클릭 → **내림차순 → 오름차순 → 해제(기본순)** 3단계, 화살표 아이콘 표시. 기본 정렬은 기존대로 원화환산 평가금액 DESC.
- **비중** = `market_value_krw ÷ summary.total_assets_krw × 100` (현금 포함 총자산 기준. 종목 합계는 100%가 아니라 (100 − 현금비중)%가 되는 것이 정상).
- 기존 필터(전체/국내/미국 · 계좌 · 통화) 유지.
- ⚠️ **5초 폴링 중 정렬·필터 상태가 초기화되지 않을 것** (정렬은 컴포넌트 state, refetch로 리셋되면 안 됨).
- 손익 색상: 상승 초록 / 하락 빨강 유지.

### 5.3 삭제
- `DataStatusPanel`을 `/portfolio`에서 제거(컴포넌트 파일은 남겨도 무방). 오류 정보는 Topbar 상태등이 대체.

## 6. 파일 소유권 (round 3)

| owner | paths |
|---|---|
| kw-api | apps/api/**, database/migrations/versions/0003_*.py |
| kw-worker | apps/worker/** |
| kw-web | apps/web/** |
| lead | 이 문서, 커밋 |

round 1~2 규칙 유지: LF, 빌더는 git commit 금지, 빌드 단계에서 docker build/up 금지(검증 단계가 수행), 계약 밖 스코프 확장 금지.

## 7. 후속(이번 라운드 밖, 합의됨)

- **자산 추이 차트**: `portfolio_snapshots`에 이미 시계열이 쌓이고 있음 → API 하나만 뚫으면 상세 페이지/메인 "최근 성과 분석"을 실데이터로 채울 수 있음.
- 정렬·필터 상태 URL 저장, 종목 클릭 → 종목 분석 페이지 연결.
