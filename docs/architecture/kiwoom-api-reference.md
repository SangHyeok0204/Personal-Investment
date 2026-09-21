# 키움 REST API 레퍼런스 (조사일: 2026-07-12)

> 조사자: kw-docs. 대상: 키움증권 Open API **REST** (구 OpenAPI+ 아님).
> 목적: worker-builder가 이 문서만 보고 국내주식 잔고/예수금 조회를 구현할 수 있게 하는 정밀 레퍼런스.
> **원칙**: 필드 하나하나에 출처 태그. 공식 문서(로그인·SPA)로 직접 확인 못 한 값은 `[TV]`(TO-VERIFY)로 명시.

## 출처 신뢰도 태그 (본문에서 각 값 옆에 표기)

| 태그 | 의미 | 신뢰도 |
|---|---|---|
| `[G]` | 공식 포털 `openapi.kiwoom.com/guide/apiguide` 에서 직접 추출 | PRIMARY (공식) |
| `[Y]` | `younghwan91/kiwoom-rest-api` Python 래퍼 **소스코드** (실 API 직접 매핑, 국내 207 엔드포인트) | SECONDARY (강) |
| `[D]` | `dongbin300/KiwoomRestApi.Net` .NET 래퍼 **소스코드** (`[JsonPropertyName]` 원시 필드명) | SECONDARY (강) |
| `[A]` | `algolab.co.kr` 2026 가이드 블로그 | SECONDARY (보강) |
| `[TV]` | 공식 원문 미확인. 구현 전 반드시 재확인 | 미확인 |

> ⚠️ 공식 포털(`openapi.kiwoom.com`)의 TR 상세 페이지는 **SPA(JS 렌더링) + 일부 로그인 게이트**라 WebFetch로 표·예시 JSON까지는 못 긁었다. 그래서 **필드명 원문은 두 오픈소스 래퍼의 소스코드**(`[Y]`/`[D]`)에서 확보했다. 이 래퍼들은 실 API에 직접 호출하는 코드라 필드명 신뢰도는 높지만, **공식 1차 출처는 아니다.** 최종 값 검증은 사용자가 로그인해 공식 문서와 대조 필요.

---

## 0. 신뢰도 요약 (섹션별)

| 섹션 | CONFIRMED | TO-VERIFY | 핵심 미확인 항목 |
|---|---|---|---|
| 1. 기본 정보 (URL) | 실전/모의 base URL, WebSocket | 미국주식 REST 지원 여부 | 미국 지원의 **공식** 확인 |
| 2. 인증 | 엔드포인트·요청/응답 필드명·`grant_type` | 토큰 유효기간(초), 재발급 시 기존토큰 무효화 여부 | 토큰 TTL, revoke 정책 |
| 3. 공통 규격 | 헤더 이름, 에러 필드(`return_code`/`return_msg`), 페이징 키 | 초당 유량제한 **공식 수치**, 페이징 키의 응답 위치(헤더 vs 바디) | rate limit 실제 숫자 |
| 4. 국내주식 계좌 TR | 엔드포인트 `/api/dostk/acnt`, api-id 목록, kt00018/kt00001 **요청·응답 필드명** | `qry_tp`/`dmst_stex_tp` **enum 값**, 숫자 포맷(문자열·부호), 공식 예시 JSON | 요청 파라미터 값, 값 포맷 |
| 5. 해외(미국)주식 | (래퍼 기준) `/api/us/acnt`, ust/usa api-id, 잔고·예수금·환율 필드명 존재 | **공식 지원 여부 전체**, 엔드포인트·필드명 공식 확인 | 미국 전체가 `[TV]` |
| 6. 구현 주의사항 | — | — | — |

**한 줄 결론(미국 REST)**: 널리 쓰이는 Python 래퍼와 algolab 가이드는 "키움 REST = 국내 중심"이라 하지만, **.NET 래퍼(`[D]`)에는 미국주식 계좌 TR(`ust2107x` 잔고, `ust2111x/2112x/2116x` 예수금·환율)이 구체 api-id·필드명까지 존재**한다 → **미국 REST는 "지원되는 것으로 강하게 추정되나 공식 미확인"**. worker는 미국을 **`[TV]` 플래그로 게이트**하고, 확인 전까지 국내만 정식 구현할 것.

---

## 1. 기본 정보 (URL, 지원 범위)

### 1.1 Base URL

| 환경 | REST Host | WebSocket Host | 출처 |
|---|---|---|---|
| 실전투자 | `https://api.kiwoom.com` | `wss://api.kiwoom.com:10000` | `[G]`·`[Y]`·`[D]` (3개 일치) |
| 모의투자 | `https://mockapi.kiwoom.com` | `wss://mockapi.kiwoom.com:10000` | `[Y]`·`[D]` (2개 일치, `[G]`는 SPA로 미노출) |

- 실전/모의는 **호스트만 다르고 경로·필드·api-id는 동일**하다 (`[Y]`/`[D]` 공통 구조). worker는 base URL만 환경변수로 스위치.
- WebSocket(`:10000`)은 실시간 시세용. 이번 잔고/예수금 동기화(REST 폴링) 범위에서는 불필요.

### 1.2 API 신청 방법 (요약)

- 공식 포털 `openapi.kiwoom.com` 로그인 → **API 사용신청** 메뉴에서 신청하면 `appkey`와 `secretkey` 발급. 이후 이 키쌍으로 접근토큰을 발급받아 사용. `[G]`·`[Y]`
- 계좌는 **로그인 계정(=appkey)에 묶인 실계좌**를 사용. 별도 "계좌 등록" 없이, 토큰의 소유자 계좌들이 조회 대상이 된다. 계좌 목록은 별도 TR로 조회(→ §4, `ka00001`). `[Y]`

### 1.3 지원 범위 (핵심 분기점)

- **국내주식 REST: 확실히 지원.** 계좌·주문·시세·차트 등 국내 200+ 엔드포인트. `[Y]`(README "국내주식 207개 엔드포인트")·`[D]`
- **해외(미국)주식 REST: 지원 강하게 추정, 공식 미확인 `[TV]`.** 근거·반대근거는 §5 참고.
- 참고: 경쟁사 한국투자증권(KIS)은 해외주식 커버리지가 넓다고 algolab이 명시 `[A]` → 미국이 키움에서 막히면 대안은 KIS.

---

## 2. 인증 (접근토큰)

### 2.1 접근토큰 발급

- **엔드포인트**: `POST /oauth2/token` `[G]`·`[Y]`·`[D]`
- **api-id(카탈로그명)**: `au10001` `[Y]` — 단, 토큰 발급 호출은 **경로 기반**(`/oauth2/token`)이며 요청에 `api-id` 헤더는 넣지 않는다(아직 토큰 없음). `au10001`은 키움 TR 카탈로그상의 식별자. `[TV: revoke가 api-id 헤더를 요구하는지]`
- **요청 헤더**: `Content-Type: application/json;charset=UTF-8` `[Y]`·`[D]`
- **요청 바디** (JSON): `[G]`·`[Y]`·`[D]`

| 필드 | 값/설명 | 출처 |
|---|---|---|
| `grant_type` | 고정 문자열 `"client_credentials"` | `[G]`·`[Y]`·`[D]` |
| `appkey` | 발급받은 앱키 | `[G]`·`[Y]`·`[D]` |
| `secretkey` | 발급받은 시크릿키 | `[G]`·`[Y]`·`[D]` |

> ⚠️ 필드명은 `secretkey` (한 단어, `secret_key` 아님). `[Y]`/`[D]` 일치.

- **응답 바디** (JSON): `[G]`(공식 guide에서 직접 확인)·`[D]`

| 필드 | 설명 | 예시값(공식 guide) | 출처 |
|---|---|---|---|
| `token` | 접근토큰 문자열 | — | `[G]`·`[D]` |
| `token_type` | 고정 `"bearer"` | `bearer` | `[G]`·`[D]` |
| `expires_dt` | **만료 절대시각** `YYYYMMDDHHMMSS` (초 단위 유효기간 아님) | `20241107083713` | `[G]`·`[D]` |
| `return_code` | `0` = 정상 | `0` | `[G]` |
| `return_msg` | `"정상적으로 처리되었습니다"` | 위 문자열 | `[G]` |

> 📌 만료는 `expires_in`(상대 초)이 **아니라** `expires_dt`(절대 타임스탬프)로 온다. worker는 이 문자열을 파싱해 만료시각을 저장하고, 만료 직전 재발급할 것. (일부 래퍼 문서에 `expires_in` 언급이 보였으나 이는 래퍼가 자체 계산한 값으로 판단 — **원 응답은 `expires_dt`**.)

### 2.2 토큰 유효기간·재발급 정책

- **유효기간(초)**: 공식 원문 미확인 `[TV]`. 커뮤니티/래퍼 관행은 **약 24시간**(algolab 예제는 만료 캐시를 ~23h로, 만료 60초 전 재발급) `[A]`. 정확한 TTL은 응답의 `expires_dt`를 신뢰하고 그 값 기준으로 관리하는 게 안전.
- **재발급 시 기존 토큰 무효화 여부**: 공식 미확인 `[TV]`. 매 요청마다 재발급하면 유량제한(→§3)에 걸린다고 다수 소스가 경고 `[A]`·`[Y]` → **토큰은 캐싱하고 만료 전 재사용**이 정석.
- **매 호출 재발급 금지**: `[Y]`/`[A]` 공통 경고. 토큰 1개 캐싱 → 만료 임박 시에만 재발급.

### 2.3 토큰 폐기 (revoke)

- **엔드포인트**: `POST /oauth2/revoke` `[Y]`
- **api-id(카탈로그명)**: `au10002` `[Y]`
- **요청 바디**: `appkey`, `secretkey`, `token` `[Y]`
- 동기화 폴링 용도에서는 굳이 revoke 불필요(만료까지 재사용). 키 회수/로그아웃 시에만.

---

## 3. 공통 요청 규격·제한

### 3.1 TR 호출 공통 헤더

접근토큰 발급 이후 모든 TR 호출은 아래 헤더를 갖는다. `[Y](base.py)`·`[A]`

| 헤더 | 값 | 필수 | 출처 |
|---|---|---|---|
| `authorization` | `Bearer {token}` (접두어 `Bearer ` + 공백) | O | `[Y]`·`[A]`·`[D]` |
| `api-id` | 호출할 TR 코드 (예: `kt00018`) | O | `[Y]`·`[A]` |
| `Content-Type` | `application/json;charset=UTF-8` | O | `[Y]`·`[A]` |
| `cont-yn` | 연속조회 여부. 첫 호출 `N`, 다음 페이지 요청 시 `Y` | 선택 | `[Y]` |
| `next-key` | 연속조회 키. 첫 호출 빈 문자열, 다음 페이지 요청 시 이전 응답의 키 | 선택 | `[Y]` |

> 헤더 이름은 **소문자·하이픈**(`api-id`, `cont-yn`, `next-key`). `authorization`도 소문자로 관찰됨 `[Y]`.

### 3.2 요청 방식

- **모든 TR은 `POST`**, 바디는 JSON. 조회성 TR도 GET이 아니라 POST. `[Y]`·`[D]`
- 어떤 TR인지는 **URL이 아니라 `api-id` 헤더**로 구분된다. 같은 카테고리는 **엔드포인트 경로가 동일**하고(예: 국내 계좌계 전부 `/api/dostk/acnt`) api-id만 바뀐다. `[Y]`

### 3.3 연속조회(페이징)

1. 첫 호출: `cont-yn: N`, `next-key: ` (빈 값). `[Y]`
2. 응답에 **연속 데이터 있으면** `cont-yn=Y` + `next-key=<키>` 가 온다.
3. 다음 페이지: 같은 TR을 `cont-yn: Y`, `next-key: <이전 키>` 헤더로 재호출.
4. `cont-yn`이 `Y`가 아니거나 `next-key`가 비면 종료. `[Y]`

> ⚠️ **페이징 키의 응답 위치**(HTTP **응답 헤더** vs **바디**)는 확정 못 함 `[TV]`. `[Y]`의 base.py는 응답을 병합한 dict에서 `cont_yn`/`next_key`(언더스코어)와 `cont-yn`/`next-key`(하이픈)를 모두 시도한다 → 키움 관행상 **응답 헤더의 `cont-yn`/`next-key`**일 가능성이 높다. worker는 헤더·바디 양쪽을 방어적으로 읽을 것.

### 3.4 공통 에러 응답

- 모든 응답에 `return_code`(정수)와 `return_msg`(문자열). `[Y]`·`[G]`
- `return_code == 0` → 성공. 그 외 → 에러. `[Y]`
- **`return_code == 5` → 요청 유량 초과**(rate limit). `[Y](base.py)` 가 이 코드를 유량초과로 보고 백오프 재시도. `[TV: 5가 유량초과라는 공식 확인]`
- worker는 `return_code != 0`이면 `return_msg`를 로깅하고, `5`(및 429류)면 지수 백오프 후 재시도.

### 3.5 요청 제한 (rate limit)

- **공식 수치 미공개 `[TV]`.** algolab·kiwoom-restful 모두 "초당 제한 있음"만 언급하고 정확한 숫자는 공식 문서로 미룸 `[A]`.
- 래퍼 기본값(보수적): **api-id(TR)별 초당 1회 + 버스트 2** (토큰버킷). `[Y](rate_limiter.py 기본 설정)`
- kiwoom-restful 패키지는 "초당 Http 연결/호출 제한 자동관리"를 기능으로 명시(수치는 없음).
- **worker 권장**: TR별로 초당 1~2회 이하로 스로틀 + `return_code=5` 백오프. 잔고/예수금은 폴링 주기(예: 수 초~수십 초)로 충분하므로 제한에 걸릴 일은 적다.

---

## 4. 국내주식 계좌 TR

### 4.1 계좌 카테고리 공통

- **엔드포인트(경로)**: `POST /api/dostk/acnt` — **국내 계좌계 TR 전부 이 경로 공유**, api-id 헤더로 구분. `[Y](account.py)`·`[D]`
- 아래는 `[Y]`에서 확인한 국내 **계좌(acnt) api-id 전량**. worker가 실제로 쓸 것은 **`kt00018`(잔고)**, **`kt00001`(예수금)**, 그리고 계좌목록 **`ka00001`**.

| api-id | 메서드(Y) | 뜻(추정) | 용도 |
|---|---|---|---|
| `kt00001` | deposit_detail | 예수금상세현황요청 | **예수금** |
| `kt00002` | daily_estimated_deposit | 일별추정예탁자산 | 참고 |
| `kt00003` | estimated_asset | 추정자산조회 | 참고 |
| `kt00004` | account_evaluation | 계좌평가현황요청 | 요약 대안 |
| `kt00005` | filled_position | 체결잔고요청 | 잔고 대안 |
| `kt00016` | daily_return_detail | 일별계좌수익률상세 | 참고 |
| `kt00017` | today_account_status | 당일계좌현황 | 참고 |
| **`kt00018`** | evaluation_balance_detail | **계좌평가잔고내역요청** | **보유종목 잔고** |
| `ka00001` | account_number_inquiry | **계좌목록/계좌번호 조회** | **계좌 목록** |

> `ka00001`(account_number_inquiry)이 **계좌 목록 조회 TR**이다. 즉 "계좌 목록 = 별도 TR". 토큰의 appkey에 묶인 계좌들을 이 TR로 열거 가능. `[Y]` (요청/응답 필드는 미확보 `[TV]`.)

### 4.2 `kt00018` 계좌평가잔고내역요청 (보유종목 잔고) — **핵심**

- **api-id**: `kt00018` / **경로**: `POST /api/dostk/acnt` `[Y]`
- **요청 바디 필드** `[D]`:

| 필드 | 뜻(추정) | 값 | 출처 |
|---|---|---|---|
| `qry_tp` | 조회구분 | enum 값 미확인 `[TV]` (.NET `KiwoomAccountEvaluationBalanceQueryType`) | `[D]` |
| `dmst_stex_tp` | 국내거래소구분 (KRX/NXT/통합) | enum 값 미확인 `[TV]` (.NET `KiwoomAccountDomesticStockExchangeType2`) | `[D]` |

> ⚠️ `qry_tp`·`dmst_stex_tp`의 **정확한 문자열 값**(예: `"0"`/`"1"`, `"KRX"`/`"NXT"`)은 공식 미확인 `[TV]`. worker는 우선 보편값(예: `qry_tp="1"`, `dmst_stex_tp="KRX"` 또는 통합)로 시도하고 응답 확인 후 고정할 것.

- **응답 — 최상위 요약 필드** `[D](KiwoomAccount.cs, [JsonPropertyName])`:

| 원시 필드 | .NET 프로퍼티 | 뜻 | 출처 |
|---|---|---|---|
| `tot_pur_amt` | TotalBuyAmount | 총매입금액 | `[D]` |
| `tot_evlt_amt` | TotalEvaluationAmount | 총평가금액 | `[D]` |
| `tot_evlt_pl` | TotalEvaluationProfitLossAmount | 총평가손익금액 | `[D]` |
| `tot_prft_rt` | TotalProfitRate | 총수익률 | `[D]` |
| `prsm_dpst_aset_amt` | EstimatedDepositAssetAmount | 추정예탁자산 | `[D]` |

- **응답 — 보유종목 배열** `acnt_evlt_remn_indv_tot` (배열 키 이름도 확인됨) `[D]`:

| 원시 필드 | .NET 프로퍼티 | 뜻 (worker 매핑) | 출처 |
|---|---|---|---|
| `stk_cd` | StockCode | **종목코드** | `[D]` |
| `stk_nm` | StockName | **종목명** | `[D]` |
| `rmnd_qty` | HoldingQuantity | **보유수량** | `[D]` |
| `pur_pric` | BuyPrice | **매입평균가** | `[D]` |
| `cur_prc` | CurrentPrice | **현재가** | `[D]` |
| `evlt_amt` | EvaluationAmount | **평가금액** | `[D]` |
| `pur_amt` | BuyAmount | **매입금액** | `[D]` |
| `evltv_prft` | EvaluationProfitLoss | **평가손익** | `[D]` |
| `prft_rt` | ProfitRate | **수익률** | `[D]` |

> ✅ 이 배열이 worker가 필요로 한 보유종목 필드(종목코드/종목명/보유수량/매입평균가/현재가/평가금액/매입금액/평가손익/수익률)를 **전부** 커버한다.

- **재구성 예시 JSON** — ⚠️ **공식 예시 미확보. 아래는 확인된 필드명으로 조립한 스캐폴드이며 값은 플레이스홀더**(실제 숫자 포맷은 §6 참고, `[TV]`). 테스트 픽스처 뼈대로만 사용:

```json
{
  "tot_pur_amt": "10000000",
  "tot_evlt_amt": "10500000",
  "tot_evlt_pl": "500000",
  "tot_prft_rt": "5.00",
  "prsm_dpst_aset_amt": "12000000",
  "acnt_evlt_remn_indv_tot": [
    {
      "stk_cd": "005930",
      "stk_nm": "삼성전자",
      "rmnd_qty": "100",
      "pur_pric": "70000",
      "cur_prc": "72000",
      "evlt_amt": "7200000",
      "pur_amt": "7000000",
      "evltv_prft": "200000",
      "prft_rt": "2.85"
    }
  ],
  "return_code": 0,
  "return_msg": "정상적으로 처리되었습니다"
}
```

### 4.3 `kt00001` 예수금상세현황요청 (예수금) — **핵심**

- **api-id**: `kt00001` / **경로**: `POST /api/dostk/acnt` `[Y]`
- **요청 바디 필드** `[D]`:

| 필드 | 뜻 | 값 | 출처 |
|---|---|---|---|
| `qry_tp` | 조회구분 | enum 값 미확인 `[TV]` (.NET `KiwoomAccountDepositQueryType`; 통상 `3`=추정조회, `2`=일반 관측되나 미확정) | `[D]` |

- **응답 — 최상위 필드** `[D](KiwoomAccount.cs)`:

| 원시 필드 | .NET 프로퍼티 | 뜻(추정) | 출처 |
|---|---|---|---|
| `entr` | Deposit | **예수금** | `[D]` |
| `profa_ch` | StockMarginCash | 주식증거금현금 | `[D]` |
| `bncr_profa_ch` | FundMarginCash | 수익증권증거금현금 | `[D]` |
| `nxdy_bncr_sell_exct` | NextDayFundSellSettlement | 익일수익증권매도정산대금 | `[D]` |
| `fc_stk_krw_repl_set_amt` | ForeignStockKrwDeposit | 해외주식 원화대용설정금 | `[D]` |
| `crd_grnta_ch` | CreditDepositCash | 신용보증금현금 | `[D]` |
| `crd_grnt_ch` | CreditCollateralCash | 신용담보금현금 | `[D]` |
| `add_grnt_ch` | AdditionalCollateralCash | 추가담보금현금 | `[D]` |
| `pymn_alow_amt` | Withdrawable | **출금가능금액** | `[D]` |
| `ord_alow_amt` | Orderable | **주문가능금액** | `[D]` |

- **응답 — 통화별 배열(Items)** `[D]`:

| 원시 필드 | .NET 프로퍼티 | 뜻 | 출처 |
|---|---|---|---|
| `crnc_cd` | CurrencyCode | 통화코드 | `[D]` |
| `fx_entr` | ForeignCurrencyDeposit | 외화예수금 | `[D]` |
| `pymn_alow_amt` | Withdrawable | 출금가능금액(해당 통화) | `[D]` |

> worker의 "예수금(원화)"은 최상위 **`entr`**, 인출가능은 **`pymn_alow_amt`**를 쓰면 된다. (배열 키 이름은 미확인 `[TV]`.)

---

## 5. 해외(미국)주식 REST

### 5.1 지원 여부 — 결론: **강하게 추정, 공식 미확인 `[TV]`**

**지원한다는 근거**:
- `[D]` .NET 래퍼에 `Objects/Models/UsStock/` 폴더와 **미국 계좌 TR이 구체 api-id·필드명까지** 존재(§5.2). 엔드포인트 경로도 `/api/us/acnt`로 도메인 계좌 `/api/dostk/acnt`와 대칭 구조. `[D]`
- 공식 포털 검색 결과에도 "해외주식(미국 포함) 계좌정보·예수금·잔고" 메뉴 언급이 보임 (단 HTS 도움말과 혼재, REST 단정 불가) `[TV]`.

**반대·주의 근거**:
- 가장 많이 쓰이는 `[Y]` Python 래퍼는 **"국내주식 207 엔드포인트"만** 구현(미국 없음).
- `[A]` algolab은 "키움 REST는 국내 중심, 해외 넓은 커버리지는 KIS 강점"이라 명시.
- 공식 포털 TR 상세가 SPA/로그인 게이트라 **미국 REST를 1차 출처로 확정하지 못함**.

→ **worker 지침**: 미국주식은 **`[TV]` 기능 플래그**로 감싸고, 확인 전엔 국내만 정식 경로로. 미국을 켤 경우 아래 §5.2 필드로 시도하되 **응답 스키마를 실호출로 검증**한 뒤 확정. 계약상 `NOT_SUPPORTED` 분기를 유지하고, 플래그가 켜지고 검증되면 활성화하는 구조를 권장.

### 5.2 (참고) 미국 계좌 TR — 전부 `[D]` 출처, 전부 `[TV]`

- **엔드포인트(추정)**: `POST /api/us/acnt` `[D](ApiEndpoint.cs; 국내 /api/dostk/* ↔ 미국 /api/us/*)`
- 주요 api-id `[D]`:

| api-id | 뜻(추정) | 비고 |
|---|---|---|
| `ust21070` | 잔고 확인 (balance) | 보유종목·평가 |
| `ust21110` | 예수금 | 원화/외화 |
| `ust21120` | 통화별 예수금·평가 | **환율 포함** |
| `ust21160` | 예수금 상세 | **USD 환율 포함** |
| `usa21670`/`usa21680`/`usa21690` | 일/월/년 계좌수익률 | 참고 |
| `usa21730` | 종목별 일수익률 | 참고 |

- 주요 응답 필드 `[D]` (전부 `[TV]`):
  - **잔고 `ust21070`**: `tot_evlt_amt`(총평가), `tot_prch_amt`(총매입), `tot_pl_amt`(총손익), `poss_qty`/`qty`(보유수량), `sell_alowq`(매도가능수량), `now_pric`(현재가), `evlt_amt`(평가금액), **`exch_rate`(환율)**.
  - **예수금 `ust21110`**: `krw_entra`(원화예수금), `fc_entra`(외화예수금), `fc_pymn_alowa`(외화출금가능), `fc_booka`(외화장부).
  - **통화별 `ust21120`**: `won_entr`(원화예수금), `fx_entr`(외화예수금), `evlt_amt`(평가), **`crnc_rt`(통화환율)**, `chg_entr`.
  - **예수금상세 `ust21160`**: `won_entr`(원화예수금), **`usd_exch_rate`(USD 환율)**, `d0_usd_fx_entr`, `d1_usd_fx_entr`(D0/D1 USD 외화예수금).

> ✅ **원화환산에 필요한 환율 필드는 존재**(`exch_rate`/`crnc_rt`/`usd_exch_rate`). 미국을 켜면 이 값으로 원화환산 가능. 단 필드명·경로 전부 공식 미확인 `[TV]`.

---

## 6. worker 구현 시 주의사항

1. **토큰**: `expires_in`(초)이 아니라 **`expires_dt`(절대시각 `YYYYMMDDHHMMSS`)** 파싱. 토큰 1개 캐싱 → 만료 임박(예: 60초 전) 재발급. **매 요청 재발급 금지**(유량초과 유발). TTL·재발급무효화 정책은 `[TV]`이므로 `expires_dt`를 신뢰.
2. **호출 방식**: 조회도 **POST + JSON 바디**. TR 구분은 URL이 아니라 **`api-id` 헤더**. 국내 계좌계는 경로 `/api/dostk/acnt` 하나에 api-id만 교체.
3. **헤더 대소문자**: `authorization`/`api-id`/`cont-yn`/`next-key` 전부 **소문자·하이픈**. `Authorization`(대문자)도 대개 통하나 관찰된 형태는 소문자 `[Y]`.
4. **페이징**: 첫 호출 `cont-yn:N`, `next-key:`(빈값). 응답의 `cont-yn=Y`면 `next-key`로 다음 페이지. **응답 키가 헤더인지 바디인지 미확정 `[TV]` → 양쪽 방어적 파싱**. 보유종목 많으면 반드시 페이징 루프.
5. **에러/유량**: `return_code!=0` → 실패, `return_msg` 로깅. `return_code==5`(유량초과 추정 `[TV]`) 또는 429 → **지수 백오프 재시도**. TR별 초당 1~2회 이하 스로틀.
6. **숫자 포맷 `[TV]`**: 키움은 금액/수량/수익률을 **문자열**로 주는 경우가 많고, 수익률에 부호·소수점 포맷 관습이 있을 수 있음(예: `"5.00"` 또는 정수 스케일). worker는 **문자열 수신 → 안전 파싱(Decimal)**, 실 응답으로 스케일 확정. 공식 예시 JSON 미확보라 이 부분은 실호출 검증 필수.
7. **요청 파라미터 값 `[TV]`**: `kt00018`의 `qry_tp`/`dmst_stex_tp`, `kt00001`의 `qry_tp` **enum 실제 값**은 미확정. 첫 통합 시 실호출로 확정하고 상수화.
8. **계좌 목록**: `ka00001`(account_number_inquiry)로 조회 `[Y]`. 요청/응답 필드는 `[TV]` → 실호출로 확인.
9. **미국주식**: §5대로 **플래그 게이트 + `NOT_SUPPORTED` 기본**. 켤 경우 `/api/us/acnt` + `ust2107x/2111x/2112x/2116x`, 원화환산은 `exch_rate`/`usd_exch_rate`. 전부 실호출 검증 후 활성화.
10. **모의투자 우선**: 실계좌 전에 `mockapi.kiwoom.com`으로 스키마·값 포맷 검증 권장(경로·필드 동일).

---

## 7. 출처 링크 전체 목록

**공식(PRIMARY) — `[G]`**
- 키움 REST API 가이드: https://openapi.kiwoom.com/guide/apiguide
- 가이드 인덱스: https://openapi.kiwoom.com/guide/index
- 포털 홈: https://openapi.kiwoom.com/
- (구) OpenAPI+ 안내(참고): https://www.kiwoom.com/h/customer/download/VOpenApiInfoView

**오픈소스 래퍼 소스코드(SECONDARY, 필드명 근거)**
- `[Y]` younghwan91/kiwoom-rest-api (Python, 국내 207 엔드포인트):
  - repo: https://github.com/younghwan91/kiwoom-rest-api
  - account.py: https://raw.githubusercontent.com/younghwan91/kiwoom-rest-api/main/src/kiwoom_rest_api/domestic/account.py
  - auth.py: https://raw.githubusercontent.com/younghwan91/kiwoom-rest-api/main/src/kiwoom_rest_api/auth.py
  - base.py: https://raw.githubusercontent.com/younghwan91/kiwoom-rest-api/main/src/kiwoom_rest_api/base.py
- `[D]` dongbin300/KiwoomRestApi.Net (.NET, 원시 JSON 필드명):
  - repo: https://github.com/dongbin300/KiwoomRestApi.Net
  - KiwoomAccount.cs (국내 계좌 응답 모델): https://raw.githubusercontent.com/dongbin300/KiwoomRestApi.Net/main/KiwoomRestApi.Net/Objects/Models/DomesticStock/KiwoomAccount.cs
  - KiwoomUsStockAccount.cs (미국 계좌 응답 모델): https://raw.githubusercontent.com/dongbin300/KiwoomRestApi.Net/main/KiwoomRestApi.Net/Objects/Models/UsStock/KiwoomUsStockAccount.cs
  - KiwoomOAuth.cs: https://raw.githubusercontent.com/dongbin300/KiwoomRestApi.Net/main/KiwoomRestApi.Net/Objects/Models/KiwoomOAuth.cs
  - ApiEndpoint.cs (경로): https://raw.githubusercontent.com/dongbin300/KiwoomRestApi.Net/main/KiwoomRestApi.Net/Objects/ApiEndpoint.cs
  - KiwoomUrls.cs (호스트): https://raw.githubusercontent.com/dongbin300/KiwoomRestApi.Net/main/KiwoomRestApi.Net/Objects/KiwoomUrls.cs

**보강(SECONDARY) — `[A]` 등**
- algolab 2026 가이드: https://algolab.co.kr/blog/kiwoom-rest-api-algotrading-guide-2026
- kiwoom-restful (PyPI): https://pypi.org/project/kiwoom-restful/
- k3.sinsa.net 구축 가이드: https://k3.sinsa.net/키움증권-rest-api로-자동매매-시스템-구축하기/

---

### 부록 A. 확인된 값 vs 미확인 값 빠른 체크리스트

**바로 써도 되는 (CONFIRMED, 복수 출처 일치)**
- base URL 2종, WebSocket 2종
- `POST /oauth2/token`, `POST /oauth2/revoke`, body `grant_type/appkey/secretkey`
- 응답 `token/token_type/expires_dt/return_code/return_msg`
- 공통 헤더 5종, POST+api-id 라우팅, 페이징 키 이름, 에러 필드
- 국내 계좌 경로 `/api/dostk/acnt`, api-id 목록
- `kt00018` 요청 필드명 2개 + 응답 요약 5필드 + 보유배열 9필드
- `kt00001` 요청 필드 + 응답 10필드 + 통화배열 3필드

**구현 전 실호출/공식대조 필요 (`[TV]`)**
- 토큰 TTL(초), 재발급 시 기존토큰 무효화 여부
- 초당 유량제한 공식 수치, `return_code=5` 의미
- 페이징 키의 응답 위치(헤더/바디)
- `qry_tp`/`dmst_stex_tp` enum 실제 값
- 숫자 필드 포맷(문자열/부호/스케일)
- 공식 예시 JSON 원문
- **미국주식 REST 전체**(지원 여부·경로 `/api/us/acnt`·`ust*` api-id·필드명)
- `ka00001` 계좌목록 요청/응답 필드
