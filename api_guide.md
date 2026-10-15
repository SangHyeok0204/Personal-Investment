# 키움 REST API 가이드

> **정본**: `docs/reference/kiwoom-rest-api-spec.json` (키움 공식 명세, TR 345개).
> 이 문서는 그 명세를 **이 프로젝트 관점으로 정리한 것**이다. 필드 하나가 의심스러우면
> 이 문서가 아니라 JSON 원본을 본다 — 이 문서는 요약이고, 원본이 사실이다.
>
> 원본 조회:
> ```bash
> python3 -c "import json;d=json.load(open('docs/reference/kiwoom-rest-api-spec.json'));\
> import sys;print(json.dumps(d['kt00018'],ensure_ascii=False,indent=1))"
> ```
>
> ⚠️`docs/architecture/kiwoom-api-reference.md` 는 공식 문서 접근 전(2026-07-12)에
> 오픈소스 래퍼를 역추적해 만든 문서다. **충돌하면 이 문서(공식 명세)가 이긴다.**

---

## 1. 공통 규격

| 항목 | 값 |
|---|---|
| 실전 도메인 | `https://api.kiwoom.com` |
| 모의 도메인 | `https://mockapi.kiwoom.com` |
| 메서드 | 전부 `POST` (조회도 POST 다) |
| Content-Type | `application/json;charset=UTF-8` |
| TR 선택 | **URL 이 아니라 `api-id` 헤더로** 고른다. 같은 URL 에 수십 개 TR 이 붙는다 |

### 요청 헤더

| 헤더 | 필수 | 설명 |
|---|---|---|
| `authorization` | ✅ | `Bearer {token}` — 접두사를 반드시 붙인다 |
| `api-id` | ✅ | TR 코드 (예: `kt00018`) |
| `cont-yn` | — | 연속조회 시 `Y` |
| `next-key` | — | 연속조회 키 |

### 연속조회(페이징)

응답 헤더의 `cont-yn` 이 `Y` 면 다음 페이지가 있다. `next-key` 를 다음 요청 헤더에
실어 보낸다. 우리 구현은 `KiwoomClient.request_tr` 이 처리하며, **헤더와 본문 양쪽에서**
읽는다(어느 쪽에 오는지 확정되지 않아 방어적으로).

### 값 포맷 — 여기서 자주 틀린다

| 현상 | 예시 | 대응 |
|---|---|---|
| 숫자가 **0 패딩 문자열** | `"000000025789890"` | `to_decimal` 이 벗긴다. int() 직접 호출 금지 |
| 환율에 **콤마** | `"1,371.70"` | 콤마 제거 후 파싱 |
| 수익률이 **퍼센트** | `"5.16"` = 5.16% | 경계에서 ÷100 하여 비율로 통일 (`_percent_to_ratio`) |
| 국내 종목코드에 **A 접두사** | `"A005930"` | `normalize_ticker` 가 벗긴다 |
| 음수가 앞에 붙음 | `"-00000000196888"` | 부호 유지하며 패딩 제거 |

### 실패 판정

**HTTP 200 이어도 실패일 수 있다.** 본문의 `return_code` 를 반드시 본다.

| return_code | 의미 |
|---|---|
| `0` | 성공 |
| `3` | 인증 실패 (메시지 안에 세부 코드) |
| `5` | 유량제한 — 백오프 후 재시도 |

### 자주 만나는 에러코드

| 코드 | 메시지 |
|---|---|
| `1501` | API ID가 Null이거나 값이 없습니다 |
| `1504` | 해당 URI에서는 지원하는 API ID가 아닙니다. API ID={?}, URI={?} |
| `1505` | 해당 API ID는 존재하지 않습니다. API ID={?} |
| `1511` | 필수 입력 값에 값이 존재하지 않습니다. 필수입력 파라미터={?} |
| `1512` | Http header에 값이 설정되지 않았거나 읽을 수 없습니다 |
| `1513` | Http Header에 authorization 필드가 설정되어 있어야 합니다 |
| `1514` | 입력으로 들어온 Http Header의 authorization 필드 형식이 맞지 않습니다 |
| `1515` | Http Header의 authorization 필드 내 Grant Type이 미리 정의된 형식이 아닙니다 |
| `1516` | Http Header의 authorization 필드 내 Token이 정의되어 있지 않습니다 |
| `1517` | 입력 값 형식이 올바르지 않습니다. 파라미터={?} 실패사유= {?} |
| `1687` | 재귀 호출이 발생하여 API 호출을 제한합니다, API ID={?} |
| `1700` | 허용된 API 요청 개수를 초과하였습니다. 유량={?}, API ID={?} |
| `1701` | 허용된 전체 요청 개수를 초과하였습니다. 총유량={?} |
| `1702` | 허용된 그룹 요청 개수를 초과하였습니다. 총유량={?}, API_ID={?} |
| `1901` | 시장 코드값이 존재하지 않습니다. 종목코드={?} |
| `1902` | 종목 정보가 없습니다. 입력한 종목코드 값을 확인바랍니다. 종목코드={?} |
| `1903` | 종목 정보가 없습니다. 입력한 종목코드, 거래소구분 값을 확인바랍니다. 거래소구분={?}, 종목코드={?} |
| `1999` | 예기치 못한 에러가 발생했습니다. 실패사유={?} |
| `8001` | App Key와 Secret Key 검증에 실패했습니다 |
| `8002` | App Key와 Secret Key 검증에 실패했습니다. 실패사유={?} |
| `8003` | Access Token을 조회하는데 실패했습니다. 실패사유={?} |
| `8005` | Token이 유효하지 않습니다 |
| `8006` | Access Token을 생성하는데 실패했습니다. 실패사유={?} |
| `8009` | Access Token을 발급하는데 실패했습니다. 실패사유={?} |
| `8010` | Token을 발급받은 IP와 서비스를 요청한 IP가 동일하지 않습니다 |
| `8011` | Access Token을 발급하는데 실패했습니다. 입력값에 grant_type이 들어오지 않았습니다 |
| `8012` | Access Token을 발급하는데 실패했습니다. grant_type의 값이 맞지 않습니다 |
| `8015` | Access Token을 폐기하는데 실패했습니다. 실패사유={?} |
| `8016` | Access Token을 폐기하는데 실패했습니다. 입력값에 Token이 들어오지 않았습니다 |
| `8020` | 입력파라미터로 appkey 또는 secretkey가 들어오지 않았습니다. |
| `8030` | 투자구분(실전/모의)이 달라서 Appkey를 사용할수가 없습니다 |
| `8031` | 투자구분(실전/모의)이 달라서 Token를 사용할수가 없습니다 |
| `8040` | 단말기 인증에 실패했습니다 |
| `8050` | IP가 등록되지 않았습니다. 키움 REST API 홈페이지 > API 사용신청 화면에서 IP를 등록해주세요. |
| `8103` | 토큰 인증 또는 단말기인증에 실패했습니다. 실패사유={?} |
| `8104` | 모의투자에서 지원하지 않는 API 입니다. |
| `8200` | 법인 고객은 해당 API를 지원하지 않습니다. API ID={?}, URI={?} |

---

## 2. 실측으로 확인된 주의사항

개조 중 실계좌에서 직접 겪은 것들이다. 명세에는 없다.

1. **IP 허용목록이 관문이다.** 등록 전에는 키가 맞아도 토큰 발급이
   `return_code=3 / "인증에 실패했습니다[8050:IP가 등록되지 않았습니다...]"` 로 거부된다.
   키움 REST API 홈페이지 > API 사용신청에서 서버 공인 IP 를 등록해야 한다.
   자격증명 오류로 오해하면 멀쩡한 키를 계속 재발급하게 된다.
2. **토큰은 계좌에 묶인다.** appkey 소유자의 계좌가 조회된다. 그래서 프로세스 안에서
   토큰 캐시를 자격증명별로 갈라야 한다 — 안 그러면 "남의 잔고가 내 화면에" 뜬다
   (예외 없이 조용히).
3. **`ust21070` 보유종목 행에 적용환율이 없을 수 있다.** 같은 묶음의 `ust21160` 이
   주는 `usd_exch_rate` 로 채운다.
4. **KRW 환산은 키움이 준 값을 쓴다.** `evlt_amt_krw` / `pl_amt_krw` 가 이미 있다.
   local × 환율로 직접 만들면 증권사 내부 환산과 소수점이 달라져 합계가 어긋난다.
5. **`qty` 가 아니라 `poss_qty` 가 실제 보유수량이다.** `qty` 는 미결제 매수분을 뺀다.
6. **`prsm_dpst_aset_amt`(추정예탁자산)는 현금이 아니다.** 현금+주식이라 현금으로
   합산하면 주식이 두 번 세어진다.
7. **계좌번호는 요청에 넣지 않는다.** 계좌계 TR 은 빈 body 를 받고, 토큰이 계좌를 정한다.

---

## 3. 이 프로젝트가 쓰는 TR

현재 호출 경로는 `apps/worker/brokers/kiwoom/` 이다. 시장 선택은 `.env` 의
`KIWOOM_MARKETS` 로 한다 (`US` / `KR` / `KR,US`).

> **표 읽는 법**: 필드명이 `- ` 로 시작하면 바로 위 배열(`result_list` 등)의
> **하위 필드**다. 예를 들어 `ust21070` 의 `- poss_qty` 는 최상위가 아니라
> `result_list[].poss_qty` 다. 최상위에서 찾다가 "명세에 없다"고 오판하기 쉽다.


### `au10001` — 접근토큰 발급

> 접근토큰 발급 — 모든 호출의 전제

- **URL**: `POST /oauth2/token`
- **설명**: 접근토큰을 발급받을 수 있습니다.

<details>
<summary>요청 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `grant_type` | grant_type | String | - | client_credentials 입력 |
| `appkey` | 앱키 | String | - |  |
| `secretkey` | 시크릿키 | String | - |  |

</details>

<details>
<summary>응답 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `expires_dt` | 만료일 | String | - |  |
| `token_type` | 토큰타입 | String | - |  |
| `token` | 접근토큰 | String | - |  |

</details>

요청 예시: `{ "grant_type": "client_credentials", "appkey": "AxserEsdcredca.....", "secretkey": "SEefdcwcforehDre2fdvc...." }`


### `ka00001` — 계좌번호조회

> 계좌 목록 — 어떤 계좌가 있는지

- **URL**: `POST /api/dostk/acnt`
- **설명**: 계좌 정보를 확인할 수 있습니다.

<details>
<summary>요청 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `authorization` | 접근토큰 | - | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 예) Bearer Egicyx... |
| `cont-yn` | 연속조회여부 | - | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| `next-key` | 연속조회키 | - | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |

</details>

<details>
<summary>응답 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `cont-yn` | 연속조회여부 | - | 1 | 다음 데이터가 있을시 Y값 전달 |
| `next-key` | 연속조회키 | - | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| `acctNo` | 계좌번호 | String | 20 | 10자리 숫자가 출력됩니다. 뒤에 2자리는 당사에서 계좌를 분류하기 위한 값입니다. |

</details>


### `kt00018` — 계좌평가잔고내역요청

> 국내 계좌평가잔고 — 보유종목 + 요약 (KIWOOM_MARKETS 에 KR 포함 시)

- **URL**: `POST /api/dostk/acnt`
- **설명**: 계좌 정보를 확인할 수 있습니다.

<details>
<summary>요청 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `authorization` | 접근토큰 | - | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 예) Bearer Egicyx... |
| `cont-yn` | 연속조회여부 | - | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| `next-key` | 연속조회키 | - | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |
| `qry_tp` | 조회구분 | String | 1 | 1:합산, 2:개별 |
| `dmst_stex_tp` | 국내거래소구분 | String | 6 | KRX:한국거래소,NXT:넥스트트레이드 |

</details>

<details>
<summary>응답 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `cont-yn` | 연속조회여부 | - | 1 | 다음 데이터가 있을시 Y값 전달 |
| `next-key` | 연속조회키 | - | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| `tot_pur_amt` | 총매입금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `tot_evlt_amt` | 총평가금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `tot_evlt_pl` | 총평가손익금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `tot_prft_rt` | 총수익률(%) | String | 12 | 단위: %, 소수점 둘째 자리까지 포맷된 백분율 |
| `prsm_dpst_aset_amt` | 추정예탁자산 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `tot_loan_amt` | 총대출금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `tot_crd_loan_amt` | 총융자금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `tot_crd_ls_amt` | 총대주금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `acnt_evlt_remn_indv_tot` | 계좌평가잔고개별합산 | List | - | Data List (Array) |
| `- stk_cd` | 종목번호 | String | 12 | 접두어 1자리 + 종목코드 6자리, 접두어(A: 주식 / J: ELW / Q: ETN) |
| `- stk_nm` | 종목명 | String | 40 | stk_cd의 종목명 |
| `- evltv_prft` | 평가손익 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- prft_rt` | 수익률(%) | String | 12 | 단위: %, 소수점 둘째 자리까지 포맷된 백분율 |
| `- pur_pric` | 매입가 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- pred_close_pric` | 전일종가 | String | 12 | 단위: 원, 좌측 0-padding 처리된 부호 포함 12자리 숫자 |
| `- rmnd_qty` | 보유수량 | String | 15 | 단위: 1주, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- trde_able_qty` | 매매가능수량 | String | 15 | 단위: 1주, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- cur_prc` | 현재가 | String | 12 | 단위: 원, 좌측 0-padding 처리된 부호 포함 12자리 숫자 |
| `- pred_buyq` | 전일매수수량 | String | 15 | 단위: 1주, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- pred_sellq` | 전일매도수량 | String | 15 | 단위: 1주, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- tdy_buyq` | 금일매수수량 | String | 15 | 단위: 1주, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- tdy_sellq` | 금일매도수량 | String | 15 | 단위: 1주, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- pur_amt` | 매입금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- pur_cmsn` | 매입수수료 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- evlt_amt` | 평가금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- sell_cmsn` | 평가수수료 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- tax` | 세금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- sum_cmsn` | 수수료합 | String | 15 | 매입수수료 + 평가수수료 |
| `- poss_rt` | 보유비중(%) | String | 12 | 단위: %, 소수점 둘째 자리까지 포맷된 백분율 |
| `- crd_tp` | 신용구분 | String | 2 | 00: 현금잔고, 03:자기융자 |
| `- crd_tp_nm` | 신용구분명 | String | 4 | 신용구분 설명 |
| `- crd_loan_dt` | 대출일 | String | 8 | YYYYMMDD |

</details>

요청 예시: `{ "qry_tp": "1", "dmst_stex_tp": "KRX" }`


### `kt00001` — 예수금상세현황요청

> 국내 예수금 상세

- **URL**: `POST /api/dostk/acnt`
- **설명**: 계좌 정보를 확인할 수 있습니다.

<details>
<summary>요청 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `authorization` | 접근토큰 | - | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 예) Bearer Egicyx... |
| `cont-yn` | 연속조회여부 | - | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| `next-key` | 연속조회키 | - | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |
| `qry_tp` | 조회구분 | String | 1 | 3:추정조회, 2:일반조회 |

</details>

<details>
<summary>응답 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `cont-yn` | 연속조회여부 | - | 1 | 다음 데이터가 있을시 Y값 전달 |
| `next-key` | 연속조회키 | - | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| `entr` | 예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `profa_ch` | 주식증거금현금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `bncr_profa_ch` | 수익증권증거금현금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `nxdy_bncr_sell_exct` | 익일수익증권매도정산대금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `fc_stk_krw_repl_set_amt` | 해외주식원화대용설정금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_grnta_ch` | 신용보증금현금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_grnt_ch` | 신용담보금현금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `add_grnt_ch` | 추가담보금현금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `etc_profa` | 기타증거금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `uncl_stk_amt` | 미수확보금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `shrts_prica` | 공매도대금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_set_grnta` | 신용설정평가금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `chck_ina_amt` | 수표입금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `etc_chck_ina_amt` | 기타수표입금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_grnt_ruse` | 신용담보재사용 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `knx_asset_evltv` | 코넥스기본예탁금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `elwdpst_evlta` | ELW예탁평가금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_ls_rght_frcs_amt` | 신용대주권리예정금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `lvlh_join_amt` | 생계형가입금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `lvlh_trns_alowa` | 생계형입금가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `repl_amt` | 대용금평가금액(합계) | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `remn_repl_evlta` | 잔고대용평가금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `trst_remn_repl_evlta` | 위탁대용잔고평가금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `bncr_remn_repl_evlta` | 수익증권대용평가금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `profa_repl` | 위탁증거금대용 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_grnta_repl` | 신용보증금대용 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_grnt_repl` | 신용담보금대용 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `add_grnt_repl` | 추가담보금대용 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `rght_repl_amt` | 권리대용금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `pymn_alow_amt` | 출금가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `wrap_pymn_alow_amt` | 랩출금가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `ord_alow_amt` | 주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `bncr_buy_alowa` | 수익증권매수가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `20stk_ord_alow_amt` | 20%종목주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `30stk_ord_alow_amt` | 30%종목주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `40stk_ord_alow_amt` | 40%종목주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `100stk_ord_alow_amt` | 100%종목주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `ch_uncla` | 현금미수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `ch_uncla_dlfe` | 현금미수연체료 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `ch_uncla_tot` | 현금미수금합계 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_int_npay` | 신용이자미납 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `int_npay_amt_dlfe` | 신용이자미납연체료 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `int_npay_amt_tot` | 신용이자미납합계 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `etc_loana` | 기타대여금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `etc_loana_dlfe` | 기타대여금연체료 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `etc_loan_tot` | 기타대여금합계 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `nrpy_loan` | 미상환융자금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `loan_sum` | 융자금합계 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `ls_sum` | 대주금합계 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `crd_grnt_rt` | 신용담보비율 | String | 15 | 단위: %, 소수점 둘째 자리까지 포맷된 백분율 |
| `mdstrm_usfe` | 중도이용료 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `min_ord_alow_yn` | 최소주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `loan_remn_evlt_amt` | 대출총평가금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `dpst_grntl_remn` | 예탁담보대출잔고 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `sell_grntl_remn` | 매도담보대출잔고 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d1_entra` | d+1추정예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d1_slby_exct_amt` | d+1매도매수정산금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d1_buy_exct_amt` | d+1매수정산금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d1_out_rep_mor` | d+1미수변제소요금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d1_sel_exct_amt` | d+1매도정산금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d1_pymn_alow_amt` | d+1출금가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d2_entra` | d+2추정예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d2_slby_exct_amt` | d+2매도매수정산금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d2_buy_exct_amt` | d+2매수정산금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d2_out_rep_mor` | d+2미수변제소요금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d2_sel_exct_amt` | d+2매도정산금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d2_pymn_alow_amt` | d+2출금가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `50stk_ord_alow_amt` | 50%종목주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `60stk_ord_alow_amt` | 60%종목주문가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `stk_entr_prst` | 종목별예수금 | List | - | Data List (Array) |
| `- crnc_cd` | 통화코드 | String | 3 | 통화코드 3자리 |
| `- fx_entr` | 외화예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- fc_krw_repl_evlta` | 원화대용평가금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- fc_trst_profa` | 해외주식증거금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- pymn_alow_amt` | 출금가능금액 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- pymn_alow_amt_entr` | 출금가능금액(예수금) | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- ord_alow_amt_entr` | 주문가능금액(예수금) | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- fc_uncla` | 외화미수(합계) | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- fc_ch_uncla` | 외화현금미수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- dly_amt` | 연체료 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- d1_fx_entr` | d+1외화예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- d2_fx_entr` | d+2외화예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- d3_fx_entr` | d+3외화예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `- d4_fx_entr` | d+4외화예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |

</details>

요청 예시: `{ "qry_tp": "3" }`


### `ust21070` — 미국주식 원장잔고확인

> 해외 원장잔고 — 보유종목 + 요약 (현재 주 경로)

- **URL**: `POST /api/us/acnt`
- **설명**: 계좌 정보를 확인할 수 있습니다.

<details>
<summary>요청 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `authorization` | 접근토큰 | - | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 예) Bearer Egicyx... |
| `cont-yn` | 연속조회여부 | - | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| `next-key` | 연속조회키 | - | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |
| `stex_tp` | 거래소구분 | String | 2 | ND:NASDAQ,NY:NYSE,NA:AMEX |
| `stk_cd` | 종목코드 | String | 12 | 미입력시 전체 |

</details>

<details>
<summary>응답 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `cont-yn` | 연속조회여부 | - | 1 | 다음 데이터가 있을시 Y값 전달 |
| `next-key` | 연속조회키 | - | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| `crnc_code` | 통화코드 | String | 3 | USD |
| `tot_evlt_amt` | 총평가금액 | String | 15 | 단위: crnc_code의 통화 |
| `tot_prch_amt` | 총매입금액 | String | 15 | 단위: crnc_code의 통화 |
| `tot_pl_amt` | 총손익금액 | String | 15 | 단위: crnc_code의 통화 |
| `tot_pl_rt` | 총수익율 | String | 8 | 단위: % |
| `tdy_book_amt` | 당일실현손익매입금액 | String | 15 | 단위: crnc_code의 통화 |
| `tdy_pl_amt` | 당일실현손익 | String | 15 | 단위: crnc_code의 통화 |
| `tdy_pl_rt` | 당일실현손익율(%) | String | 8 | 단위: % |
| `tot_evlt_amt_krw` | 총평가금액(원) | String | 15 | 단위: 원 |
| `tot_prch_amt_krw` | 총매입금액(원) | String | 15 | 단위: 원 |
| `tot_pl_amt_krw` | 총손익금액(원) | String | 15 | 단위: 원 |
| `tdy_book_amt_krw` | 당일실현손익매입금액(원) | String | 15 | 단위: 원 |
| `tdy_pl_amt_krw` | 당일실현손익(원) | String | 15 | 단위: 원 |
| `result_list` | 결과리스트 | List | - | Data List (Array) |
| `- stex_nm` | 거래소명 | String | 30 | stex_tp의 거래소명 |
| `- crnc_code` | 통화코드 | String | 3 | USD |
| `- stk_cd` | 종목코드 | String | 12 | 티커 |
| `- frgn_stk_nm` | 종목명 | String | 50 | stk_cd의 종목명 |
| `- qty` | 결제기준수량 | String | 12 | 단위: 1주, 결제까지 완료된 수량 |
| `- poss_qty` | 보유수량 | String | 12 | 단위: 1주 |
| `- sell_alowq` | 매도가능수량 | String | 12 | 단위: 1주 |
| `- pred_cntr_sellq` | 전일매도수량 | String | 12 | 단위: 1주 |
| `- pred_cntr_buyq` | 전일매수수량 | String | 12 | 단위: 1주 |
| `- tdy_cntr_sellq` | 금일매도수량 | String | 12 | 단위: 1주 |
| `- tdy_cntr_buyq` | 금일매수수량 | String | 12 | 단위: 1주 |
| `- frgn_stk_book_uv` | 매입단가 | String | 12 | 단위: crnc_code의 통화 |
| `- now_pric` | 현재가 | String | 12 | 단위: crnc_code의 통화 |
| `- evlt_amt` | 평가금액 | String | 12 | 단위: crnc_code의 통화 |
| `- pl_amt` | 손익금액 | String | 12 | 단위: crnc_code의 통화 |
| `- pl_rt` | 손익율(%) | String | 8 | 단위: % |
| `- evlt_amt_krw` | 평가금액(원) | String | 12 | 단위: 원 |
| `- pl_amt_krw` | 손익금액(원) | String | 12 | 단위: 원 |
| `- natn_nm` | 국가명 | String | 40 | 미국 |
| `- exch_rate` | 환율 | String | 12 | crnc_code의 환율 |
| `- frgn_stk_book_uv_krw` | 매입단가(원) | String | 12 | 단위: 원 |
| `- now_pric_krw` | 현재가(원) | String | 12 | 단위: 원 |
| `- frgn_stk_book_amt` | 매입금액 | String | 12 | 단위: crnc_code의 통화 |
| `- frgn_stk_book_amt_krw` | 매입금액(원) | String | 12 | 단위: 원 |

</details>

요청 예시: `{ "stex_tp": "", "stk_cd": "" }`


### `ust21110` — 해외주식 예수금

> 해외 예수금 (통화별)

- **URL**: `POST /api/us/acnt`
- **설명**: 계좌 정보를 확인할 수 있습니다.

<details>
<summary>요청 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `authorization` | 접근토큰 | - | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 예) Bearer Egicyx... |
| `cont-yn` | 연속조회여부 | - | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| `next-key` | 연속조회키 | - | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |

</details>

<details>
<summary>응답 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `cont-yn` | 연속조회여부 | - | 1 | 다음 데이터가 있을시 Y값 전달 |
| `next-key` | 연속조회키 | - | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| `krw_entra` | 원화예수금 | String | 15 | 단위: 원 |
| `ch_uncla` | 현금미수금 | String | 15 | 단위: 원 |
| `etc_loana` | 기타대여금 | String | 15 | 단위: 원 |
| `result_list` | 결과리스트 | List | - | Data List (Array) |
| `- crnc_code` | 통화코드 | String | 3 | USD |
| `- crnc_nm` | 통화명 | String | 20 | crnc_code의 통화명 |
| `- fc_entra` | 외화예수금 | String | 15 | 단위: crnc_code의 통화 |
| `- fc_pymn_alowa` | 외화출금가능금액 | String | 15 | 단위: crnc_code의 통화 |
| `- futr_repl_profa` | 선물대용증거금 | String | 15 | 단위: crnc_code의 통화 |
| `- fc_booka` | 외화장부금액 | String | 15 | 단위: 원 |
| `- fc_ord_alowa` | 외화주문가능금액 | String | 15 | 단위: crnc_code의 통화 |
| `- futr_profa_booka` | 선물증거금장부금액 | String | 15 | 단위: 원 |
| `- fc_ch_uncla` | 외화현금미수금 | String | 15 | 단위: crnc_code의 통화 |
| `- fc_etc_loana` | 외화기타대여금 | String | 15 | 단위: crnc_code의 통화 |

</details>


### `ust21160` — 미국주식 예수금 상세

> 해외 예수금 상세 — usd_exch_rate 의 유일한 출처

- **URL**: `POST /api/us/acnt`
- **설명**: 계좌 정보를 확인할 수 있습니다.

<details>
<summary>요청 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `authorization` | 접근토큰 | - | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 예) Bearer Egicyx... |
| `cont-yn` | 연속조회여부 | - | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| `next-key` | 연속조회키 | - | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |

</details>

<details>
<summary>응답 필드</summary>

| 필드 | 이름 | 타입 | 길이 | 설명 |
|---|---|---|---|---|
| `api-id` | TR명 | - | 10 | 8자리 TR코드, ex) ka00001, usa10099 |
| `cont-yn` | 연속조회여부 | - | 1 | 다음 데이터가 있을시 Y값 전달 |
| `next-key` | 연속조회키 | - | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| `won_entr` | 원화 예수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `won_dfr_amt` | 미수금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `won_etc_loana` | 기타 대여금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `krw_ord_set_amt` | 해외원화주문설정금 | String | 12 | 단위: 원, 좌측 0-padding 처리된 부호 포함 12자리 숫자 |
| `usd_exch_rate` | 매도환율(USD) | String | 12 | 세자릿수 콤마, 소수점 둘째 자리까지 포맷된 숫자 |
| `d0_setl_dt` | D0 국내결제일자 | String | 8 | YYYYMMDD |
| `d0_won_conv_alow_ch` | D0 원화환산추정인출가능금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d0_usd_fx_entr` | D0 외화예수금(USD) | String | 15 | 단위: USD |
| `d1_setl_dt` | D1 국내결제일자 | String | 8 | YYYYMMDD |
| `d1_won_conv_alow_ch` | D1 원화환산추정인출가능금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d1_usd_fx_entr` | D1 외화예수금(USD) | String | 15 | 단위: USD |
| `d1_usd_exct_amt` | D1 해외정산금(USD) | String | 15 | 단위: USD |
| `d1_usd_buy_excta` | D1 해외매수정산금(USD) | String | 15 | 단위: USD |
| `d1_usd_sell_excta` | D1 해외매도정산금(USD) | String | 15 | 단위: USD |
| `d2_setl_dt` | D2 국내결제일자 | String | 8 | YYYYMMDD |
| `d2_won_conv_alow_ch` | D2 원화환산추정인출가능금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d2_usd_fx_entr` | D2 외화예수금(USD) | String | 15 | 단위: USD |
| `d2_usd_exct_amt` | D2 해외정산금(USD) | String | 15 | 단위: USD |
| `d2_usd_buy_excta` | D2 해외매수정산금(USD) | String | 15 | 단위: USD |
| `d2_usd_sell_excta` | D2 해외매도정산금(USD) | String | 15 | 단위: USD |
| `d3_setl_dt` | D3 국내결제일자 | String | 8 | YYYYMMDD |
| `d3_won_conv_alow_ch` | D3 원화환산추정인출가능금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d3_usd_fx_entr` | D3 외화예수금(USD) | String | 15 | 단위: USD |
| `d3_usd_exct_amt` | D3 해외정산금(USD) | String | 15 | 단위: USD |
| `d3_usd_buy_excta` | D3 해외매수정산금(USD) | String | 15 | 단위: USD |
| `d3_usd_sell_excta` | D3 해외매도정산금(USD) | String | 15 | 단위: USD |
| `d4_setl_dt` | D4 국내결제일자 | String | 8 | YYYYMMDD |
| `d4_won_conv_alow_ch` | D4 원화환산추정인출가능금 | String | 15 | 단위: 원, 좌측 0-padding 처리된 부호 포함 15자리 숫자 |
| `d4_usd_fx_entr` | D4 외화예수금(USD) | String | 15 | 단위: USD |
| `d4_usd_exct_amt` | D4 해외정산금(USD) | String | 15 | 단위: USD |
| `d4_usd_buy_excta` | D4 해외매수정산금(USD) | String | 15 | 단위: USD |
| `d4_usd_sell_excta` | D4 해외매도정산금(USD) | String | 15 | 단위: USD |

</details>

---

## 4. 다음에 쓸 TR (로드맵 연결)

화면 골격은 있는데 데이터가 없는 자리들이다. 어느 TR 을 붙이면 되는지 미리 정해 둔다.

| TR | 이름 | 쓸 곳 |
|---|---|---|
| `ust21100` | 미국주식 거래내역 | 매매 이력 화면(/trading/executions)의 원천 후보 |
| `ust21150` | 미국주식 일별 주문체결내역 | 일자별 체결 — 매매일지 자동 초안 |
| `ust21180` | 미국주식 기간별 주문내역 | 기간 조회가 필요할 때 |
| `ust21530` | 미국주식 실현손익 | /trading/realized |
| `ust21640` | 미국주식 일별 종목별 실현손익 | 종목별 손익 기여 |
| `ust21661` | 미국주식 월별 실현손익 | 월별 실현손익 차트 |
| `usa21670` | 미국주식 일별계좌수익률현황 | /portfolio/performance#returns — 자산 추이·수익률의 지름길 |
| `usa21680` | 미국주식 월별계좌수익률현황 | 월별 수익률 |
| `usa21690` | 미국주식 연도별계좌수익률현황 | 연도별 수익률 |
| `usa21730` | 미국주식 일별종목수익률현황 | 종목별 기여도 분석 |
| `ust31301` | 환율 조회 | USD/KRW — 외화 환산이 필요한 모든 곳 |
| `usa20100` | 미국주식 현재가 종목정보 | 시세 소스 대안(토스 대신 키움으로도 가능) |
| `usa20590` | 미국주식 일별주가 | 보유 종목 가격 시계열 |
| `usa10099` | 미국주식 종목리스트 | 종목 마스터 — 섹터/ETF 분류의 기반 |
| `usa10104` | 미국 ETF,ETN 리스트 | ETF 판별 |
| `usa10105` | 미국 ETF 카테고리 리스트 | ETF 분류 |
| `usa24300` | 미국주식 리서치(미국주식/ETF) | /research 라이브러리 보강 후보 |

---

## 5. 전체 TR 카탈로그

346개 전부. 필드가 필요하면 JSON 원본에서 그 `api-id` 를 꺼내 본다.


### 인증 (2)

| api-id | 이름 | URL |
|---|---|---|
| `au10001` | 접근토큰 발급 | `/oauth2/token` |
| `au10002` | 접근토큰폐기 | `/oauth2/revoke` |

### 해외 · 계좌 (28)

| api-id | 이름 | URL |
|---|---|---|
| `usa21670` | 미국주식 일별계좌수익률현황 | `/api/us/acnt` |
| `usa21680` | 미국주식 월별계좌수익률현황 | `/api/us/acnt` |
| `usa21690` | 미국주식 연도별계좌수익률현황 | `/api/us/acnt` |
| `usa21730` | 미국주식 일별종목수익률현황 | `/api/us/acnt` |
| `usa21731` | 미국주식 월별종목수익률현황 | `/api/us/acnt` |
| `usa21732` | 미국주식 연도별종목수익률현황 | `/api/us/acnt` |
| `ust21050` | 미국주식 원장 미체결 | `/api/us/acnt` |
| `ust21070` | 미국주식 원장잔고확인 | `/api/us/acnt` |
| `ust21100` | 미국주식 거래내역 | `/api/us/acnt` |
| `ust21110` | 해외주식 예수금 | `/api/us/acnt` |
| `ust21111` | 원화출금가능 금액 조회(원화대용 포함) | `/api/us/acnt` |
| `ust21120` | 통화별 예수금 및 증권 평가금현황 | `/api/us/acnt` |
| `ust21121` | 해외증권 원장 평가금액현황 | `/api/us/acnt` |
| `ust21131` | 해외증권 특정일 평가금액 | `/api/us/acnt` |
| `ust21132` | 특정일 통화별 예수금 및 증권 평가금 | `/api/us/acnt` |
| `ust21150` | 미국주식 일별 주문체결내역 | `/api/us/acnt` |
| `ust21160` | 미국주식 예수금 상세 | `/api/us/acnt` |
| `ust21170` | 미국주식 당일 종목별 실현손익 | `/api/us/acnt` |
| `ust21180` | 미국주식 기간별 주문내역 | `/api/us/acnt` |
| `ust21510` | 미국주식 당일 주문체결 확인 | `/api/us/acnt` |
| `ust21530` | 미국주식 실현손익 | `/api/us/acnt` |
| `ust21610` | 미국주식 당일매매 | `/api/us/acnt` |
| `ust21620` | 미국주식 당일매매정리 | `/api/us/acnt` |
| `ust21630` | 미국주식 당일 실현손익 | `/api/us/acnt` |
| `ust21640` | 미국주식 일별 종목별 실현손익 | `/api/us/acnt` |
| `ust21650` | 미국주식 기간별 수익률 현황 | `/api/us/acnt` |
| `ust21660` | 미국주식 일별 실현손익 | `/api/us/acnt` |
| `ust21661` | 미국주식 월별 실현손익 | `/api/us/acnt` |

### 해외 · 환전/환율 (3)

| api-id | 이름 | URL |
|---|---|---|
| `ust31300` | 환전 예상 금액 조회 | `/api/us/exchange` |
| `ust31301` | 환율 조회 | `/api/us/exchange` |
| `ust31302` | 환전 신청 | `/api/us/exchange` |

### 해외 · 시세 (5)

| api-id | 이름 | URL |
|---|---|---|
| `usa20100` | 미국주식 현재가 종목정보 | `/api/us/mrkcond` |
| `usa20101` | 미국주식 현재가 10호가 | `/api/us/mrkcond` |
| `usa20150` | 미국주식 상세 체결내역 | `/api/us/mrkcond` |
| `usa20151` | 미국주식 일별 체결내역 | `/api/us/mrkcond` |
| `usa20590` | 미국주식 일별주가 | `/api/us/mrkcond` |

### 해외 · 종목정보 (34)

| api-id | 이름 | URL |
|---|---|---|
| `usa10098` | 미국주식 거래소구분 조회 | `/api/us/stkinfo` |
| `usa10099` | 미국주식 종목리스트 | `/api/us/stkinfo` |
| `usa10100` | 미국주식 종목 조회 | `/api/us/stkinfo` |
| `usa10101` | 미국주식 업종리스트 | `/api/us/stkinfo` |
| `usa10102` | 미국지수 리스트 | `/api/us/stkinfo` |
| `usa10103` | 미국주식 종목메모 조회 | `/api/us/stkinfo` |
| `usa10104` | 미국 ETF,ETN 리스트 | `/api/us/stkinfo` |
| `usa10105` | 미국 ETF 카테고리 리스트 | `/api/us/stkinfo` |
| `usa20520` | 미국주식 거래량급등락(주식/업종) | `/api/us/stkinfo` |
| `usa20521` | 미국주식 거래량급등락(ETF) | `/api/us/stkinfo` |
| `usa20570` | 미국주식 가격대별주가(주식/업종) | `/api/us/stkinfo` |
| `usa20571` | 미국주식 가격대별주가(ETF) | `/api/us/stkinfo` |
| `usa20930` | 미국주식 가격급등락(주식/업종) | `/api/us/stkinfo` |
| `usa20931` | 미국주식 가격급등락(ETF) | `/api/us/stkinfo` |
| `usa20932` | 미국주식 가격급등락(관심종목) | `/api/us/stkinfo` |
| `usa20970` | 미국주식 고가/저가 접근(주식/업종) | `/api/us/stkinfo` |
| `usa20971` | 미국주식 고가/저가 접근(ETF) | `/api/us/stkinfo` |
| `usa20972` | 미국주식 고가/저가 접근(관심종목) | `/api/us/stkinfo` |
| `usa23400` | 미국주식 거래량갱신(주식/업종) | `/api/us/stkinfo` |
| `usa23401` | 미국주식 거래량갱신(ETF) | `/api/us/stkinfo` |
| `usa23402` | 미국주식 거래량갱신(관심종목) | `/api/us/stkinfo` |
| `usa24100` | 미국주식 신고가/신저가(주식/업종) | `/api/us/stkinfo` |
| `usa24101` | 미국주식 신고가/신저가(ETF) | `/api/us/stkinfo` |
| `usa24140` | 미국주식 갭상승/갭하락(주식/업종) | `/api/us/stkinfo` |
| `usa24141` | 미국주식 갭상승/갭하락(ETF) | `/api/us/stkinfo` |
| `usa24210` | 미국주식 잔량률급증(주식/업종) | `/api/us/stkinfo` |
| `usa24211` | 미국주식 잔량률급증(ETF) | `/api/us/stkinfo` |
| `usa24220` | 미국주식 매물대집중(주식/업종) | `/api/us/stkinfo` |
| `usa24221` | 미국주식 매물대집중(ETF) | `/api/us/stkinfo` |
| `usa26410` | 미국주식 연도별 등락률(종목) | `/api/us/stkinfo` |
| `usa26411` | 미국주식 연도별 업종별 종목등락률 | `/api/us/stkinfo` |
| `usa26412` | 미국주식 연도별 ETF 카테고리별 종목등락률 | `/api/us/stkinfo` |
| `usa26413` | 미국주식 연도별 등락률(업종) | `/api/us/stkinfo` |
| `usa26414` | 미국주식 연도별 등락률(ETF) | `/api/us/stkinfo` |

### 해외 · 차트 (7)

| api-id | 이름 | URL |
|---|---|---|
| `usa06010` | 미국주식 틱 차트 | `/api/us/chart` |
| `usa06011` | 미국주식 분 차트 | `/api/us/chart` |
| `usa06012` | 미국주식 일 차트 | `/api/us/chart` |
| `usa06013` | 미국주식 주 차트 | `/api/us/chart` |
| `usa06014` | 미국주식 월 차트 | `/api/us/chart` |
| `usa06015` | 미국주식 년 차트 | `/api/us/chart` |
| `usa06016` | 미국주식 분기 차트 | `/api/us/chart` |

### 해외 · 주문 (10)

| api-id | 이름 | URL |
|---|---|---|
| `ust20000` | 미국주식 매수 주문 | `/api/us/ordr` |
| `ust20001` | 미국주식 매도 주문 | `/api/us/ordr` |
| `ust20002` | 미국주식 정정 주문 | `/api/us/ordr` |
| `ust20003` | 미국주식 취소 주문 | `/api/us/ordr` |
| `ust21200` | 미국주식 예약 매수주문 | `/api/us/ordr` |
| `ust21201` | 미국주식 예약 매도주문 | `/api/us/ordr` |
| `ust21203` | 미국주식 예약주문 취소 | `/api/us/ordr` |
| `ust21204` | 미국주식 일자별 예약내역 조회 | `/api/us/ordr` |
| `ust21205` | 미국주식 예약주문 내역조회 | `/api/us/ordr` |
| `ust31490` | 미국주식 주문가능수량(종목/증거금률별) | `/api/us/ordr` |

### 해외 · 순위 (35)

| api-id | 이름 | URL |
|---|---|---|
| `usa01980` | 미국주식 실시간 종목 조회 순위 | `/api/us/rkinfo` |
| `usa01990` | 미국주식 관심종목 등록 상위 | `/api/us/rkinfo` |
| `usa20510` | 미국주식 기간별 등락률상위(주식/업종) | `/api/us/rkinfo` |
| `usa20511` | 미국주식 기간별 등락률상위(ETF) | `/api/us/rkinfo` |
| `usa20512` | 미국주식 기간별 등락률상위(관심종목) | `/api/us/rkinfo` |
| `usa20530` | 미국주식 당일 거래량 상위(주식/업종) | `/api/us/rkinfo` |
| `usa20531` | 미국주식 당일 거래량 상위(ETF) | `/api/us/rkinfo` |
| `usa20540` | 미국주식 당일 거래대금 상위(주식/업종) | `/api/us/rkinfo` |
| `usa20541` | 미국주식 당일 거래대금 상위(ETF) | `/api/us/rkinfo` |
| `usa20550` | 미국주식 시가총액상위(주식/업종) | `/api/us/rkinfo` |
| `usa20551` | 미국주식 시가총액상위(ETF) | `/api/us/rkinfo` |
| `usa20880` | 키움 거래 상위 종목(미국주식) | `/api/us/rkinfo` |
| `usa20881` | 키움 거래 상위 종목(미국 ETF) | `/api/us/rkinfo` |
| `usa20910` | 미국주식 전일대비 등락률상위(주식/업종) | `/api/us/rkinfo` |
| `usa20911` | 미국주식 전일대비 등락률상위(ETF) | `/api/us/rkinfo` |
| `usa20920` | 미국주식 시가대비 등락률상위(주식/업종) | `/api/us/rkinfo` |
| `usa20921` | 미국주식 시가대비 등락률상위(ETF) | `/api/us/rkinfo` |
| `usa20922` | 미국주식 시가대비 등락률상위(관심종목) | `/api/us/rkinfo` |
| `usa20940` | 미국주식 누적 등락률 상위(주식/업종) | `/api/us/rkinfo` |
| `usa20941` | 미국주식 누적 등락률 상위(ETF) | `/api/us/rkinfo` |
| `usa20960` | 미국주식 전일 거래상위(주식/업종) | `/api/us/rkinfo` |
| `usa20961` | 미국주식 전일 거래상위(ETF) | `/api/us/rkinfo` |
| `usa24110` | 미국주식 최고최저가대비 상승하락(주식/업종) | `/api/us/rkinfo` |
| `usa24111` | 미국주식 최고최저가대비 상승하락(ETF) | `/api/us/rkinfo` |
| `usa24120` | 미국주식 특정일자 상승/하락 (주식/업종) | `/api/us/rkinfo` |
| `usa24121` | 미국주식 특정일자 상승/하락(ETF) | `/api/us/rkinfo` |
| `usa24150` | 미국주식 회전율 상위(주식/업종) | `/api/us/rkinfo` |
| `usa24151` | 미국주식 회전율 상위(ETF) | `/api/us/rkinfo` |
| `usa24160` | 미국주식 연속상승/하락 순위(주식/업종) | `/api/us/rkinfo` |
| `usa24161` | 미국주식 연속상승/하락 순위(ETF) | `/api/us/rkinfo` |
| `usa24162` | 미국주식 연속상승/하락 순위(관심종목) | `/api/us/rkinfo` |
| `usa24200` | 미국주식 호가잔량상위(주식/업종) | `/api/us/rkinfo` |
| `usa24201` | 미국주식 호가잔량상위(ETF) | `/api/us/rkinfo` |
| `usa24290` | 미국주식 주간거래 괴리율 상위(주식/업종) | `/api/us/rkinfo` |
| `usa24291` | 미국주식 주간거래 괴리율 상위(ETF) | `/api/us/rkinfo` |

### 해외 · 업종 (2)

| api-id | 이름 | URL |
|---|---|---|
| `usa23000` | 미국주식 업종별 기간별 수익률 조회 | `/api/us/sect` |
| `usa23100` | 미국주식 업종별 등락률 상위/하위 조회 | `/api/us/sect` |

### 해외 · 관심종목 (2)

| api-id | 이름 | URL |
|---|---|---|
| `usa20200` | 미국주식 관심종목 그룹 리스트 조회 | `/api/us/watchlist` |
| `usa20201` | 미국주식 관심종목 그룹 상세 조회 | `/api/us/watchlist` |

### 해외 · 리서치 (1)

| api-id | 이름 | URL |
|---|---|---|
| `usa24300` | 미국주식 리서치(미국주식/ETF) | `/api/us/invtinfo` |

### 국내 · 계좌 (33)

| api-id | 이름 | URL |
|---|---|---|
| `ka00001` | 계좌번호조회 | `/api/dostk/acnt` |
| `ka01690` | 일별잔고수익률 | `/api/dostk/acnt` |
| `ka10072` | 일자별종목별실현손익요청_일자 | `/api/dostk/acnt` |
| `ka10073` | 일자별종목별실현손익요청_기간 | `/api/dostk/acnt` |
| `ka10074` | 일자별실현손익요청 | `/api/dostk/acnt` |
| `ka10075` | 미체결요청 | `/api/dostk/acnt` |
| `ka10076` | 체결요청 | `/api/dostk/acnt` |
| `ka10077` | 당일실현손익상세요청 | `/api/dostk/acnt` |
| `ka10085` | 계좌수익률요청 | `/api/dostk/acnt` |
| `ka10088` | 미체결 분할주문 상세 | `/api/dostk/acnt` |
| `ka10170` | 당일매매일지요청 | `/api/dostk/acnt` |
| `kt00001` | 예수금상세현황요청 | `/api/dostk/acnt` |
| `kt00002` | 일별추정예탁자산현황요청 | `/api/dostk/acnt` |
| `kt00003` | 추정자산조회요청 | `/api/dostk/acnt` |
| `kt00004` | 계좌평가현황요청 | `/api/dostk/acnt` |
| `kt00005` | 체결잔고요청 | `/api/dostk/acnt` |
| `kt00007` | 계좌별주문체결내역상세요청 | `/api/dostk/acnt` |
| `kt00008` | 계좌별익일결제예정내역요청 | `/api/dostk/acnt` |
| `kt00009` | 계좌별주문체결현황요청 | `/api/dostk/acnt` |
| `kt00010` | 주문인출가능금액요청 | `/api/dostk/acnt` |
| `kt00011` | 증거금율별주문가능수량조회요청 | `/api/dostk/acnt` |
| `kt00012` | 신용보증금율별주문가능수량조회요청 | `/api/dostk/acnt` |
| `kt00013` | 증거금세부내역조회요청 | `/api/dostk/acnt` |
| `kt00015` | 위탁종합거래내역요청 | `/api/dostk/acnt` |
| `kt00016` | 일별계좌수익률상세현황요청 | `/api/dostk/acnt` |
| `kt00017` | 계좌별당일현황요청 | `/api/dostk/acnt` |
| `kt00018` | 계좌평가잔고내역요청 | `/api/dostk/acnt` |
| `kt50020` | 금현물 잔고확인 | `/api/dostk/acnt` |
| `kt50021` | 금현물 예수금 | `/api/dostk/acnt` |
| `kt50030` | 금현물 주문체결전체조회 | `/api/dostk/acnt` |
| `kt50031` | 금현물 주문체결조회 | `/api/dostk/acnt` |
| `kt50032` | 금현물 거래내역조회 | `/api/dostk/acnt` |
| `kt50075` | 금현물 미체결조회 | `/api/dostk/acnt` |

### 국내 · 시세 (24)

| api-id | 이름 | URL |
|---|---|---|
| `ka10004` | 주식호가요청 | `/api/dostk/mrkcond` |
| `ka10005` | 주식일주월시분요청 | `/api/dostk/mrkcond` |
| `ka10006` | 주식시분요청 | `/api/dostk/mrkcond` |
| `ka10007` | 시세표성정보요청 | `/api/dostk/mrkcond` |
| `ka10011` | 신주인수권전체시세요청 | `/api/dostk/mrkcond` |
| `ka10044` | 일별기관매매종목요청 | `/api/dostk/mrkcond` |
| `ka10045` | 종목별기관매매추이요청 | `/api/dostk/mrkcond` |
| `ka10046` | 체결강도추이시간별요청 | `/api/dostk/mrkcond` |
| `ka10047` | 체결강도추이일별요청 | `/api/dostk/mrkcond` |
| `ka10063` | 장중투자자별매매요청 | `/api/dostk/mrkcond` |
| `ka10066` | 장마감후투자자별매매요청 | `/api/dostk/mrkcond` |
| `ka10078` | 증권사별종목매매동향요청 | `/api/dostk/mrkcond` |
| `ka10086` | 일별주가요청 | `/api/dostk/mrkcond` |
| `ka50010` | 금현물체결추이 | `/api/dostk/mrkcond` |
| `ka50012` | 금현물일별추이 | `/api/dostk/mrkcond` |
| `ka50087` | 금현물예상체결 | `/api/dostk/mrkcond` |
| `ka50100` | 금현물 시세정보 | `/api/dostk/mrkcond` |
| `ka50101` | 금현물 호가 | `/api/dostk/mrkcond` |
| `ka90005` | 프로그램매매추이요청 시간대별 | `/api/dostk/mrkcond` |
| `ka90006` | 프로그램매매차익잔고추이요청 | `/api/dostk/mrkcond` |
| `ka90007` | 프로그램매매누적추이요청 | `/api/dostk/mrkcond` |
| `ka90008` | 종목시간별프로그램매매추이요청 | `/api/dostk/mrkcond` |
| `ka90010` | 프로그램매매추이요청 일자별 | `/api/dostk/mrkcond` |
| `ka90013` | 종목일별프로그램매매추이요청 | `/api/dostk/mrkcond` |

### 국내 · 종목정보 (32)

| api-id | 이름 | URL |
|---|---|---|
| `ka00198` | 실시간종목조회순위 | `/api/dostk/stkinfo` |
| `ka10001` | 주식기본정보요청 | `/api/dostk/stkinfo` |
| `ka10002` | 주식거래원요청 | `/api/dostk/stkinfo` |
| `ka10003` | 체결정보요청 | `/api/dostk/stkinfo` |
| `ka10013` | 신용매매동향요청 | `/api/dostk/stkinfo` |
| `ka10015` | 일별거래상세요청 | `/api/dostk/stkinfo` |
| `ka10016` | 신고저가요청 | `/api/dostk/stkinfo` |
| `ka10017` | 상하한가요청 | `/api/dostk/stkinfo` |
| `ka10018` | 고저가근접요청 | `/api/dostk/stkinfo` |
| `ka10019` | 가격급등락요청 | `/api/dostk/stkinfo` |
| `ka10024` | 거래량갱신요청 | `/api/dostk/stkinfo` |
| `ka10025` | 매물대집중요청 | `/api/dostk/stkinfo` |
| `ka10026` | 고저PER요청 | `/api/dostk/stkinfo` |
| `ka10028` | 시가대비등락률요청 | `/api/dostk/stkinfo` |
| `ka10043` | 거래원매물대분석요청 | `/api/dostk/stkinfo` |
| `ka10052` | 거래원순간거래량요청 | `/api/dostk/stkinfo` |
| `ka10054` | 변동성완화장치발동종목요청 | `/api/dostk/stkinfo` |
| `ka10055` | 당일전일체결량요청 | `/api/dostk/stkinfo` |
| `ka10058` | 투자자별일별매매종목요청 | `/api/dostk/stkinfo` |
| `ka10059` | 종목별투자자기관별요청 | `/api/dostk/stkinfo` |
| `ka10061` | 종목별투자자기관별합계요청 | `/api/dostk/stkinfo` |
| `ka10084` | 당일전일체결요청 | `/api/dostk/stkinfo` |
| `ka10095` | 지정종목 정보요청 | `/api/dostk/stkinfo` |
| `ka10099` | 종목정보 리스트 | `/api/dostk/stkinfo` |
| `ka10100` | 종목정보 조회 | `/api/dostk/stkinfo` |
| `ka10101` | 업종코드 리스트 | `/api/dostk/stkinfo` |
| `ka10102` | 회원사 리스트 | `/api/dostk/stkinfo` |
| `ka10103` | 종목메모 조회 | `/api/dostk/stkinfo` |
| `ka90003` | 프로그램순매수상위50요청 | `/api/dostk/stkinfo` |
| `ka90004` | 종목별프로그램매매현황요청 | `/api/dostk/stkinfo` |
| `kt20016` | 신용융자 가능종목요청 | `/api/dostk/stkinfo` |
| `kt20017` | 신용융자 가능문의 | `/api/dostk/stkinfo` |

### 국내 · 차트 (21)

| api-id | 이름 | URL |
|---|---|---|
| `ka10060` | 종목별투자자기관별차트요청 | `/api/dostk/chart` |
| `ka10064` | 장중투자자별매매차트요청 | `/api/dostk/chart` |
| `ka10079` | 주식틱차트조회요청 | `/api/dostk/chart` |
| `ka10080` | 주식분봉차트조회요청 | `/api/dostk/chart` |
| `ka10081` | 주식일봉차트조회요청 | `/api/dostk/chart` |
| `ka10082` | 주식주봉차트조회요청 | `/api/dostk/chart` |
| `ka10083` | 주식월봉차트조회요청 | `/api/dostk/chart` |
| `ka10094` | 주식년봉차트조회요청 | `/api/dostk/chart` |
| `ka20004` | 업종틱차트조회요청 | `/api/dostk/chart` |
| `ka20005` | 업종분봉조회요청 | `/api/dostk/chart` |
| `ka20006` | 업종일봉조회요청 | `/api/dostk/chart` |
| `ka20007` | 업종주봉조회요청 | `/api/dostk/chart` |
| `ka20008` | 업종월봉조회요청 | `/api/dostk/chart` |
| `ka20019` | 업종년봉조회요청 | `/api/dostk/chart` |
| `ka50079` | 금현물틱차트조회요청 | `/api/dostk/chart` |
| `ka50080` | 금현물분봉차트조회요청 | `/api/dostk/chart` |
| `ka50081` | 금현물일봉차트조회요청 | `/api/dostk/chart` |
| `ka50082` | 금현물주봉차트조회요청 | `/api/dostk/chart` |
| `ka50083` | 금현물월봉차트조회요청 | `/api/dostk/chart` |
| `ka50091` | 금현물당일틱차트조회요청 | `/api/dostk/chart` |
| `ka50092` | 금현물당일분봉차트조회요청 | `/api/dostk/chart` |

### 국내 · 주문 (8)

| api-id | 이름 | URL |
|---|---|---|
| `kt10000` | 주식 매수주문 | `/api/dostk/ordr` |
| `kt10001` | 주식 매도주문 | `/api/dostk/ordr` |
| `kt10002` | 주식 정정주문 | `/api/dostk/ordr` |
| `kt10003` | 주식 취소주문 | `/api/dostk/ordr` |
| `kt50000` | 금현물 매수주문 | `/api/dostk/ordr` |
| `kt50001` | 금현물 매도주문 | `/api/dostk/ordr` |
| `kt50002` | 금현물 정정주문 | `/api/dostk/ordr` |
| `kt50003` | 금현물 취소주문 | `/api/dostk/ordr` |

### 국내 · 신용주문 (4)

| api-id | 이름 | URL |
|---|---|---|
| `kt10006` | 신용 매수주문 | `/api/dostk/crdordr` |
| `kt10007` | 신용 매도주문 | `/api/dostk/crdordr` |
| `kt10008` | 신용 정정주문 | `/api/dostk/crdordr` |
| `kt10009` | 신용 취소주문 | `/api/dostk/crdordr` |

### 국내 · 순위 (25)

| api-id | 이름 | URL |
|---|---|---|
| `ka00190` | 대량체결상위 | `/api/dostk/rkinfo` |
| `ka00196` | 체결금액대별매매비중 | `/api/dostk/rkinfo` |
| `ka04196` | 수익률상위고객매매상세 | `/api/dostk/rkinfo` |
| `ka10020` | 호가잔량상위요청 | `/api/dostk/rkinfo` |
| `ka10021` | 호가잔량급증요청 | `/api/dostk/rkinfo` |
| `ka10022` | 잔량율급증요청 | `/api/dostk/rkinfo` |
| `ka10023` | 거래량급증요청 | `/api/dostk/rkinfo` |
| `ka10027` | 전일대비등락률상위요청 | `/api/dostk/rkinfo` |
| `ka10029` | 예상체결등락률상위요청 | `/api/dostk/rkinfo` |
| `ka10030` | 당일거래량상위요청 | `/api/dostk/rkinfo` |
| `ka10031` | 전일거래량상위요청 | `/api/dostk/rkinfo` |
| `ka10032` | 거래대금상위요청 | `/api/dostk/rkinfo` |
| `ka10033` | 신용비율상위요청 | `/api/dostk/rkinfo` |
| `ka10034` | 외인기간별매매상위요청 | `/api/dostk/rkinfo` |
| `ka10035` | 외인연속순매매상위요청 | `/api/dostk/rkinfo` |
| `ka10036` | 외인한도소진율증가상위 | `/api/dostk/rkinfo` |
| `ka10037` | 외국계창구매매상위요청 | `/api/dostk/rkinfo` |
| `ka10038` | 종목별증권사순위요청 | `/api/dostk/rkinfo` |
| `ka10039` | 증권사별매매상위요청 | `/api/dostk/rkinfo` |
| `ka10040` | 당일주요거래원요청 | `/api/dostk/rkinfo` |
| `ka10042` | 순매수거래원순위요청 | `/api/dostk/rkinfo` |
| `ka10053` | 당일상위이탈원요청 | `/api/dostk/rkinfo` |
| `ka10062` | 동일순매매순위요청 | `/api/dostk/rkinfo` |
| `ka10065` | 장중투자자별매매상위요청 | `/api/dostk/rkinfo` |
| `ka90009` | 외국인기관매매상위요청 | `/api/dostk/rkinfo` |

### 국내 · 업종 (6)

| api-id | 이름 | URL |
|---|---|---|
| `ka10010` | 업종프로그램요청 | `/api/dostk/sect` |
| `ka10051` | 업종별투자자순매수요청 | `/api/dostk/sect` |
| `ka20001` | 업종현재가요청 | `/api/dostk/sect` |
| `ka20002` | 업종별주가요청 | `/api/dostk/sect` |
| `ka20003` | 전업종지수요청 | `/api/dostk/sect` |
| `ka20009` | 업종현재가일별요청 | `/api/dostk/sect` |

### 국내 · ETF (9)

| api-id | 이름 | URL |
|---|---|---|
| `ka40001` | ETF수익율요청 | `/api/dostk/etf` |
| `ka40002` | ETF종목정보요청 | `/api/dostk/etf` |
| `ka40003` | ETF일별추이요청 | `/api/dostk/etf` |
| `ka40004` | ETF전체시세요청 | `/api/dostk/etf` |
| `ka40006` | ETF시간대별추이요청 | `/api/dostk/etf` |
| `ka40007` | ETF시간대별체결요청 | `/api/dostk/etf` |
| `ka40008` | ETF일자별체결요청 | `/api/dostk/etf` |
| `ka40009` | ETF시간대별NAV현황 | `/api/dostk/etf` |
| `ka40010` | ETF시간대별수급현황 | `/api/dostk/etf` |

### 국내 · ELW (11)

| api-id | 이름 | URL |
|---|---|---|
| `ka10048` | ELW일별민감도지표요청 | `/api/dostk/elw` |
| `ka10050` | ELW민감도지표요청 | `/api/dostk/elw` |
| `ka30001` | ELW가격급등락요청 | `/api/dostk/elw` |
| `ka30002` | 거래원별ELW순매매상위요청 | `/api/dostk/elw` |
| `ka30003` | ELWLP보유일별추이요청 | `/api/dostk/elw` |
| `ka30004` | ELW괴리율요청 | `/api/dostk/elw` |
| `ka30005` | ELW조건검색요청 | `/api/dostk/elw` |
| `ka30009` | ELW등락율순위요청 | `/api/dostk/elw` |
| `ka30010` | ELW잔량순위요청 | `/api/dostk/elw` |
| `ka30011` | ELW근접율요청 | `/api/dostk/elw` |
| `ka30012` | ELW종목상세정보요청 | `/api/dostk/elw` |

### 국내 · 테마 (2)

| api-id | 이름 | URL |
|---|---|---|
| `ka90001` | 테마그룹별요청 | `/api/dostk/thme` |
| `ka90002` | 테마구성종목요청 | `/api/dostk/thme` |

### 국내 · 대차 (4)

| api-id | 이름 | URL |
|---|---|---|
| `ka10068` | 대차거래추이요청 | `/api/dostk/slb` |
| `ka10069` | 대차거래상위10종목요청 | `/api/dostk/slb` |
| `ka20068` | 대차거래추이요청(종목별) | `/api/dostk/slb` |
| `ka90012` | 대차거래내역요청 | `/api/dostk/slb` |

### 국내 · 외국인/기관 (3)

| api-id | 이름 | URL |
|---|---|---|
| `ka10008` | 주식외국인종목별매매동향 | `/api/dostk/frgnistt` |
| `ka10131` | 기관외국인연속매매현황요청 | `/api/dostk/frgnistt` |
| `ka52301` | 금현물투자자현황 | `/api/dostk/frgnistt` |

### 국내 · 관심종목 (2)

| api-id | 이름 | URL |
|---|---|---|
| `ka01300` | 관심종목 그룹 리스트 조회 | `/api/dostk/watchlist` |
| `ka01301` | 관심종목 그룹 상세 조회 | `/api/dostk/watchlist` |

### 국내 · 기타 (1)

| api-id | 이름 | URL |
|---|---|---|
| `ka10014` | 공매도추이요청 | `/api/dostk/shsa` |

### 실시간(WebSocket) (31)

| api-id | 이름 | URL |
|---|---|---|
| `00` | 주문체결 | `/api/websocket` |
| `04` | 잔고 | `/api/websocket` |
| `0A` | 주식기세 | `/api/websocket` |
| `0B` | 주식체결 | `/api/websocket` |
| `0C` | 주식우선호가 | `/api/websocket` |
| `0D` | 주식호가잔량 | `/api/websocket` |
| `0E` | 주식시간외호가 | `/api/websocket` |
| `0F` | 주식당일거래원 | `/api/websocket` |
| `0G` | ETF NAV | `/api/websocket` |
| `0H` | 주식예상체결 | `/api/websocket` |
| `0I` | 국제금환산가격 | `/api/websocket` |
| `0J` | 업종지수 | `/api/websocket` |
| `0U` | 업종등락 | `/api/websocket` |
| `0g` | 주식종목정보 | `/api/websocket` |
| `0m` | ELW 이론가 | `/api/websocket` |
| `0s` | 장시작시간 | `/api/websocket` |
| `0u` | ELW 지표 | `/api/websocket` |
| `0w` | 종목프로그램매매 | `/api/websocket` |
| `1h` | VI발동/해제 | `/api/websocket` |
| `F4` | 미국주식 실시간 주문 확인 | `/api/websocket` |
| `F5` | 미국주식 실시간 체결 | `/api/websocket` |
| `FE` | 미국주식 실시간 체결가 | `/api/websocket` |
| `FT` | 미국주식 10호가 | `/api/websocket` |
| `ka10171` | 조건검색 목록조회 | `/api/websocket` |
| `ka10172` | 조건검색 요청 일반 | `/api/websocket` |
| `ka10173` | 조건검색 요청 실시간 | `/api/websocket` |
| `ka10174` | 조건검색 실시간 해제 | `/api/websocket` |
| `usa20280` | 미국주식 조건검색 목록조회 | `/api/websocket` |
| `usa20281` | 미국주식 조건검색 요청 일반 | `/api/websocket` |
| `usa20290` | 미국주식 조건검색 요청 실시간 | `/api/websocket` |
| `usa20291` | 미국주식 조건검색 실시간 해제 | `/api/websocket` |
