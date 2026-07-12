# 자산 추이 차트 스펙 (BINDING — round 4)

메인 대시보드의 "최근 성과 분석" 플레이스홀더를 **시점별 총자산 실데이터**로 대체한다.
선행 문서: `contract.md`, `contract-kiwoom.md`, `portfolio-detail-spec.md`.

## 0. 데이터 현실 (설계의 전제 — 반드시 인지할 것)

2026-07-12 기준 실측:
- `portfolio_snapshots` = **6행, 전부 오늘, 총자산 값이 전부 동일**(45,275,025.83). `position_snapshots` = 72행(6×12).
- 스냅샷은 **동기화할 때만** 생성된다. 오늘 처음 연동했으므로 과거 이력은 **없고, 소급 생성 불가**(키움 잔고 TR은 현재 상태만 반환. 과거 포트폴리오 가치를 만들려면 과거 시세 소스가 필요한데 없음).
- 오늘은 일요일(장 마감) → 몇 번을 동기화해도 같은 값.

**따라서**: 차트는 "지금 당장 멋있어 보이는 것"이 아니라 "시간이 지나면 의미가 생기는 것"으로 설계한다. **데이터가 부족할 때 그럴듯한 선을 그리지 말고, 축적 중임을 정직하게 표시한다.** 가짜 데이터·보간·목업 금지.

**벤치마크(KOSPI 등) 라인은 이번 범위 밖.** 시세 소스가 없다. 참조 디자인(`reference/index.png`)에는 벤치마크 선이 있지만, 데이터 없이 그리면 거짓말이 된다. 자리만 비워두고 "미연동"으로 둔다.

## 1. API (kw-api — `apps/api/**`)

**`GET /api/v1/portfolio/history`**

쿼리 파라미터:
| param | 기본 | 설명 |
|---|---|---|
| `days` | 90 | 조회 기간(일). 1~730. |
| `exclude_tickers` | 없음 | 쉼표 구분 티커 목록. 지정 시 해당 종목을 제외하고 재계산(§1.2). |

응답:
```json
{
  "points": [
    {"date":"2026-07-12","snapshot_at":"2026-07-12T13:19:33Z",
     "total_assets_krw":45275025.83,"securities_value_krw":39374173.0,
     "cash_value_krw":5900852.83,"total_purchase_amount_krw":38922660.9,
     "total_unrealized_pnl_krw":274550.0,"unrealized_return_pct":0.71}
  ],
  "distinct_days": 1,
  "first_snapshot_at": "2026-07-12T07:55:20Z",
  "last_snapshot_at": "2026-07-12T13:19:33Z",
  "excluded_tickers": []
}
```

### 1.1 집계 규칙
- **하루 1점**: 같은 날짜(KST 기준)에 스냅샷이 여러 개면 **그날의 마지막 스냅샷**만 쓴다. (오늘처럼 하루 6번 동기화해도 점 1개.)
- 날짜 경계는 **Asia/Seoul**. DB는 UTC 저장이므로 `snapshot_at AT TIME ZONE 'Asia/Seoul'`로 버킷팅.
- 계좌가 여러 개면 같은 시점의 계좌별 스냅샷을 **합산**(현재 1계좌).
- `unrealized_return_pct` = pnl ÷ purchase × 100 (purchase가 0이면 null). **저장값이 없으므로 계산이지만, 이건 비율 정의 그 자체이지 파생 재구성이 아니다.**
- 오름차순(과거→현재) 정렬.

### 1.2 `exclude_tickers` — 대시보드 필터와의 정합성 (중요)
메인 대시보드는 `EXCLUDED_DASHBOARD_TICKERS`(현재 000660, SKHYV, 388720, GLD)로 일부 종목을 **표시 계층에서만** 제외한다. 스냅샷은 전체 기준이므로, 차트를 그대로 붙이면 **같은 화면에서 카드(3,533만)와 차트(4,528만)가 어긋난다** — 이 프로젝트에서 반복적으로 사고를 낸 "숫자가 조용히 불일치" 유형이다.

`exclude_tickers`가 오면 `position_snapshots` + `assets`를 조인해 재계산한다:
- `securities_value_krw` = Σ `position_snapshots.market_value_krw` (제외 티커 뺀 것)
- `total_purchase_amount_krw` = Σ `quantity × average_purchase_price × exchange_rate` (제외 티커 뺀 것. position_snapshots에 매입금액 컬럼이 없어 이렇게 도출 — 환율도 그 행에 저장돼 있으니 우리가 FX를 만드는 게 아니다)
- `total_unrealized_pnl_krw` = Σ `position_snapshots.unrealized_pnl_krw` (제외 티커 뺀 것)
- `cash_value_krw` = `portfolio_snapshots.cash_value_krw` 그대로 (현금은 종목 제외와 무관)
- `total_assets_krw` = 위 securities + cash
- 파라미터 없으면 `portfolio_snapshots`의 저장값을 그대로 사용(빠른 경로).

**불변식(테스트로 고정)**: `exclude_tickers` 없이 호출한 마지막 점의 `total_assets_krw` == `GET /portfolio/overview`의 `summary.total_assets_krw`. 두 API가 같은 사실을 다르게 말하면 안 된다.

### 1.3 테스트
- 하루에 스냅샷 3개 → 점 1개(마지막 것)로 접히는지
- KST 날짜 경계(UTC 15:00 = KST 자정 다음날) 처리
- `exclude_tickers` 적용 시 securities/pnl/purchase가 줄고 cash는 그대로
- 위 불변식(history 마지막 점 == overview 총자산)
- 스냅샷 0개 → `points: []`, `distinct_days: 0` (404 아님)

## 2. Web (kw-web — `apps/web/**`)

메인 대시보드(`app/page.tsx`)의 "최근 성과 분석" 카드를 실데이터로 교체.

- 데이터: `GET /api/v1/portfolio/history?days=90&exclude_tickers=<EXCLUDED_DASHBOARD_TICKERS>` — **대시보드의 제외 필터를 그대로 전달**해 카드 숫자와 차트가 일치하게 한다(§1.2).
- 차트: **인라인 SVG 라인 차트**(도넛과 같은 원칙 — 새 차트 라이브러리 금지). Y = 총자산(KRW), X = 날짜. 그리드는 은은하게, 마지막 점 강조, hover 시 값 툴팁(선택).
- 기간 토글(1개월/3개월/6개월/전체)은 있어도 되지만, 데이터가 없으면 의미 없으므로 **전체/90일 기본**으로 시작.
- ⚠️ **`distinct_days < 2`면 차트를 그리지 말 것.** 대신 축적 중 상태를 표시:
  > "자산 추이는 동기화 기록이 쌓이면 표시됩니다.
  > 현재 1일치 · 최초 기록 2026-07-12
  > 매일 자동 동기화를 켜면 하루 한 점씩 쌓입니다."
  점 1개로 직선을 긋거나 보간해서 그럴듯하게 보이게 하는 것 **금지**.
- 벤치마크(KOSPI) 라인: **그리지 않는다.** 범례에 "벤치마크 미연동"으로만 표기하거나 아예 생략.
- Best/Worst 박스(참조 디자인)는 현재 보유 종목의 수익률 최고/최저로 채울 수 있음(이미 있는 데이터) — 유지.

## 3. n8n 자동 동기화 (kw-infra — `workflows/n8n/**`, `README.md`)

**차트가 의미를 가지려면 매일 점이 찍혀야 한다.** 지금은 수동 동기화뿐이라 데이터가 안 쌓인다.

- `workflows/n8n/portfolio/sync-kiwoom-portfolio-scheduled.json` 신규:
  - Schedule Trigger(Cron) → HTTP Request `POST http://api:8000/internal/jobs`, 헤더 `X-Internal-API-Key`, body `{"job_type":"SYNC_KIWOOM_PORTFOLIO","payload":{}}`
  - 크론: **평일 16:10 KST**(국내장 마감 후) + **매일 06:30 KST**(미국장 마감 후, 서머타임 양쪽 커버). 두 트리거 or 크론 두 개.
  - 최상위 `"id"` 필수(CLI import 요구사항 — round 2에서 확인됨).
  - `GENERIC_TIMEZONE=Asia/Seoul`이 이미 compose에 있으므로 크론은 KST 기준.
- ⚠️ **워크플로를 자동 활성화하지 말 것.** import만 하고, 사용자가 n8n UI에서 Active 토글을 켜도록 README에 안내. (자동으로 켜면 사용자가 모르는 사이 외부 API를 주기 호출하게 된다.)
- README에 "자산 추이 차트를 채우려면 자동 동기화를 켜세요" 절 추가 + import 명령 + 활성화 방법.

## 4. 파일 소유권

| owner | paths |
|---|---|
| kw-api | apps/api/** |
| kw-web | apps/web/** |
| kw-infra | workflows/n8n/**, README.md |
| lead | 이 문서, 커밋 |

마이그레이션 불필요(스냅샷 테이블은 이미 존재). 빌더는 git commit 금지.
