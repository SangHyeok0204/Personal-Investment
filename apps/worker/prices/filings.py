"""SEC EDGAR 공시 — 보유 종목이 무엇을 신고했나.

키가 필요 없다. 다만 SEC 는 **연락처가 담긴 User-Agent** 를 요구한다
(`www.sec.gov` 는 일반 UA 에 403 을 준다. `data.sec.gov` 는 관대하다).
`.env` 의 `SEC_USER_AGENT` 로 바꿀 수 있고, 안 넣으면 앱 이름만으로 요청한다 —
사용자 이메일을 말없이 외부로 보내지 않는다.

★이 모듈의 요점은 "최근 공시 목록"이 아니라 **무엇이 중요한 공시인가**다.
  실측(NVDA 최근 1001건): Form 4 가 556건, Form 144 가 247건으로 **803건이
  임원 서류**다. 실제로 읽을 만한 건 8-K 62 · 10-Q 19 · 10-K 6, 합쳐 87건뿐이다.
  그대로 나열하면 중요한 공시가 서류 더미에 묻힌다 — 그래서 분류한다.

⚠️ETF 는 개별 기업 공시 대상이 **아니다**(신탁 단위로 낸다). 보유 17종목 중
  8개가 ETF 다. 이걸 "공시 없음"이라고 적으면 거짓말이 된다 — `reason` 으로
  구분한다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import httpx

# ★(계획 A3a) SEC 요청은 공용 클라이언트를 거친다 — 프로세스당 속도 제한 + 403 이면 10분 멈춤.
#   예전에는 4스레드가 제한 없이 동시에 불렀다.
from sec.client import SecBlocked, sec_client, sec_get
from sec.client import user_agent as _sec_user_agent

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

_DEFAULT_UA = "Personal-Investment-Dashboard/1.0 (dashboard@personal-investment.local)"


def user_agent() -> str:
    """SEC 에 보낼 UA. 사용자가 `.env` 에 넣으면 그 값을 쓴다(`sec.client` 와 같은 규칙)."""
    return _sec_user_agent()


# ── 서식 분류 ────────────────────────────────────────────────────────────────
# ⚠️'중요도'를 우리가 매기지 않는다. 서식의 **성격**으로 나눌 뿐이다 —
#   어떤 8-K 가 중요한지는 내용을 읽어야 알 수 있고, 우리는 그걸 모른다.

CATEGORY_RESULTS = "실적·정기"
CATEGORY_EVENT = "수시"
CATEGORY_OWNERSHIP = "지분"
CATEGORY_INSIDER = "내부자"
CATEGORY_OTHER = "기타"

_FORM_INFO: dict[str, tuple[str, str]] = {
    "10-K": ("연간보고서", CATEGORY_RESULTS),
    "10-Q": ("분기보고서", CATEGORY_RESULTS),
    "20-F": ("외국기업 연차보고서", CATEGORY_RESULTS),
    "40-F": ("캐나다기업 연차보고서", CATEGORY_RESULTS),
    "ARS": ("주주용 연차보고서", CATEGORY_RESULTS),
    "11-K": ("종업원지주 연간보고", CATEGORY_RESULTS),
    "8-K": ("수시보고", CATEGORY_EVENT),
    "6-K": ("외국기업 수시보고", CATEGORY_EVENT),
    "DEF 14A": ("주주총회 위임장", CATEGORY_EVENT),
    "PRE 14A": ("주주총회 위임장 (예비)", CATEGORY_EVENT),
    "DEFA14A": ("위임장 추가자료", CATEGORY_OTHER),
    "PX14A6G": ("주주 의견 제출", CATEGORY_OTHER),
    "S-1": ("증권신고서", CATEGORY_EVENT),
    "S-3": ("증권신고서 (약식)", CATEGORY_EVENT),
    "S-3ASR": ("증권신고서 (자동효력)", CATEGORY_EVENT),
    "S-4": ("합병·교환 증권신고서", CATEGORY_EVENT),
    "425": ("합병 관련 안내자료", CATEGORY_EVENT),
    "424B": ("증권신고 최종 설명서", CATEGORY_EVENT),
    "FWP": ("발행 관련 추가 안내", CATEGORY_OTHER),
    "EFFECT": ("증권신고 효력 발생", CATEGORY_OTHER),
    "S-8": ("임직원 주식보상 등록", CATEGORY_OTHER),
    "S-8 POS": ("주식보상 등록 정정", CATEGORY_OTHER),
    "8-A12B": ("증권 등록 (상장)", CATEGORY_EVENT),
    "25-NSE": ("상장폐지 통지", CATEGORY_EVENT),
    "CERT": ("거래소 상장 승인", CATEGORY_OTHER),
    "CORRESP": ("SEC 서신 왕래", CATEGORY_OTHER),
    "UPLOAD": ("SEC 검토 의견", CATEGORY_OTHER),
    "SD": ("분쟁광물 보고", CATEGORY_OTHER),
    "IRANNOTICE": ("이란 제재 관련 고지", CATEGORY_OTHER),
    "N-PX": ("의결권 행사 기록", CATEGORY_OTHER),
    "SC 13D": ("5%↑ 지분 (경영참여)", CATEGORY_OWNERSHIP),
    "SC 13G": ("5%↑ 지분 (단순투자)", CATEGORY_OWNERSHIP),
    "13F-HR": ("기관 보유내역", CATEGORY_OWNERSHIP),
    "3": ("내부자 최초 보고", CATEGORY_INSIDER),
    "4": ("내부자 매매", CATEGORY_INSIDER),
    "5": ("내부자 연간 보고", CATEGORY_INSIDER),
    "144": ("제한주식 매도 신고", CATEGORY_INSIDER),
}


def normalize_form(form: str) -> tuple[str, bool]:
    """서식 코드를 기준형 + 정정여부로 나눈다.

    ⚠️표를 계속 늘리는 방식은 **썩는다.** 실측에서 `4/A`·`3/A`·`144/A` 가
      매핑에 없어 **내부자 서식 13건이 '기타'로 새고** 있었다. `/A`(정정)는
      규칙이므로 규칙으로 처리한다.

    ⚠️SEC 는 같은 서식을 `SC 13G` 와 `SCHEDULE 13G` 두 이름으로 준다(실측:
      최근 1년 보유 종목에서 SCHEDULE 13G/A 48건, SCHEDULE 13G 21건).
    """
    code = (form or "").strip().upper()
    amended = code.endswith("/A")
    if amended:
        code = code[:-2].strip()
    if code.startswith("SCHEDULE "):
        code = "SC " + code[len("SCHEDULE "):]
    # 424B2/B3/B5/B7 … 은 모두 같은 성격의 최종 설명서다.
    if code.startswith("424B"):
        code = "424B"
    return code, amended


# 8-K 항목 코드. "8-K 2.02" 는 아무 뜻도 전달하지 못한다 — "실적 발표"여야 한다.
_ITEM_LABELS: dict[str, str] = {
    "1.01": "중요 계약 체결",
    "1.02": "중요 계약 해지",
    "1.03": "파산·법정관리",
    "1.05": "사이버 보안 사고",
    "2.01": "자산 취득·처분",
    "2.02": "실적 발표",
    "2.03": "채무 발생",
    "2.04": "기한이익 상실",
    "2.05": "구조조정 비용 확정",
    "2.06": "자산 손상 확정",
    "3.01": "상장규정 위반·상장폐지",
    "3.02": "미등록 주식 발행",
    "3.03": "주주 권리 변경",
    "4.01": "회계법인 변경",
    "4.02": "과거 재무제표 신뢰 불가",
    "5.01": "지배권 변동",
    "5.02": "임원 선임·사임",
    "5.03": "정관 변경·회계연도 변경",
    "5.05": "윤리강령 변경",
    "5.07": "주주총회 결과",
    "5.08": "주주제안 관련",
    "7.01": "Reg FD 공시",
    "8.01": "기타 사건",
    "9.01": "재무제표·첨부자료",
}


def form_label(form: str) -> str:
    """사람이 읽을 이름. **모르는 서식은 지어내지 않고 코드 그대로 둔다.**"""
    code, amended = normalize_form(form)
    label = _FORM_INFO.get(code, (code, CATEGORY_OTHER))[0]
    return f"{label} (정정)" if amended else label


def form_category(form: str) -> str:
    code, _ = normalize_form(form)
    return _FORM_INFO.get(code, (code, CATEGORY_OTHER))[1]


def item_label(code: str) -> str:
    return _ITEM_LABELS.get(code, code)


@dataclass(frozen=True)
class Filing:
    ticker: str
    company: str | None
    form: str
    form_label: str
    category: str
    filed_date: date
    report_date: date | None
    items: list[str]
    item_labels: list[str]
    url: str


@dataclass(frozen=True)
class TickerFilings:
    """한 종목의 조회 결과.

    ⚠️`ok=False` 와 `filings=[]` 는 다른 상태다. 전자는 "못 받았다",
      후자는 "받았는데 없다" — 화면에서 둘을 같은 말로 적으면 안 된다.
    """

    ticker: str
    cik: str | None
    company: str | None
    ok: bool
    reason: str | None
    filings: list[Filing] = field(default_factory=list)
    #: 최근 구간(기본 90일)의 내부자 서식(3/4/5/144) 건수. 개별 나열은 하지 않는다.
    #: ⚠️나열해 봐야 쓸모가 없다 — SEC 제출 목록에는 **누가 냈는지가 없어서**
    #:   "4 · 내부자 보고 · 09-22" 505줄이 될 뿐이다. 이름과 매수/매도는 서식
    #:   원문을 건마다 받아야 나온다.
    insider_count: int = 0
    #: 그중 **최근 1/3 구간**(기본 30일)에 몰린 건수. 갑자기 몰리는 것 자체가
    #: 신호다(락업 해제·베스팅 등). ⚠️방향은 모른다 — 서식 4 는 매수·매도·부여를
    #: 모두 담는다. 화면에서도 "팔고 있다"고 쓰지 않는다.
    insider_recent_count: int = 0
    #: 상한에 걸려 잘렸는지. ⚠️조용히 자르면 합쳐 보는 피드에 **구멍**이 생긴다
    #: (실측: 상한 25 에서 GOOGL 59건 중 34건이 사라졌다). 잘렸으면 말한다.
    truncated: bool = False


def _client(timeout: float) -> httpx.Client:
    return sec_client(timeout)


def fetch_cik_map(timeout: float = 15.0) -> dict[str, tuple[str, str]]:
    """ticker → (10자리 CIK, 회사명). 실패하면 빈 dict (전체를 죽이지 않는다).

    ⚠️ETF 는 이 목록에 **없다**. 없다고 해서 조회 실패가 아니다.
    """
    try:
        with _client(timeout) as client:
            response = sec_get(client, TICKER_MAP_URL)
            if response.status_code != 200:
                return {}
            raw = response.json()
    except Exception:
        return {}

    out: dict[str, tuple[str, str]] = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker") or "").upper()
        cik = entry.get("cik_str")
        if ticker and cik is not None:
            out[ticker] = (f"{int(cik):010d}", str(entry.get("title") or ""))
    return out


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _one(
    client: httpx.Client,
    ticker: str,
    cik: str,
    company: str,
    since: date,
    insider_since: date,
    insider_recent_since: date,
    limit: int,
) -> TickerFilings:
    try:
        response = sec_get(client, SUBMISSIONS_URL.format(cik=cik))
        if response.status_code != 200:
            return TickerFilings(
                ticker=ticker, cik=cik, company=company, ok=False,
                reason=f"SEC 응답 {response.status_code}",
            )
        recent = (response.json().get("filings") or {}).get("recent") or {}
    except SecBlocked:
        return TickerFilings(
            ticker=ticker, cik=cik, company=company, ok=False,
            reason="SEC 403 차단 — 10분 쉰 뒤 다시 받습니다",
        )
    except Exception as exc:  # 네트워크·JSON 어느 쪽이든 한 종목만 비운다.
        return TickerFilings(
            ticker=ticker, cik=cik, company=company, ok=False,
            reason=f"조회 실패 ({type(exc).__name__})",
        )

    forms = recent.get("form") or []
    filed = recent.get("filingDate") or []
    reported = recent.get("reportDate") or []
    items = recent.get("items") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []

    filings: list[Filing] = []
    insider = 0
    insider_recent = 0
    truncated = False
    numeric_cik = str(int(cik))

    for i, form in enumerate(forms):
        filed_date = _parse_date(filed[i] if i < len(filed) else None)
        if filed_date is None:
            continue
        category = form_category(form)
        if category == CATEGORY_INSIDER:
            # 개별로 싣지 않고 센다 — 556건을 나열하면 나머지가 안 보인다.
            # (그리고 제출 목록에는 누가 냈는지가 없어 나열해도 읽을 것이 없다.)
            if filed_date >= insider_since:
                insider += 1
                if filed_date >= insider_recent_since:
                    insider_recent += 1
            continue
        if filed_date < since:
            continue
        if len(filings) >= limit:
            truncated = True
            continue

        codes = [
            c.strip()
            for c in str(items[i] if i < len(items) else "").split(",")
            if c.strip()
        ]
        accession = accessions[i] if i < len(accessions) else ""
        document = documents[i] if i < len(documents) else ""
        filings.append(
            Filing(
                ticker=ticker,
                company=company,
                form=form,
                form_label=form_label(form),
                category=category,
                filed_date=filed_date,
                report_date=_parse_date(reported[i] if i < len(reported) else None),
                items=codes,
                item_labels=[item_label(c) for c in codes],
                url=ARCHIVE_URL.format(
                    cik=numeric_cik,
                    accession=accession.replace("-", ""),
                    document=document,
                ),
            )
        )

    return TickerFilings(
        ticker=ticker, cik=cik, company=company, ok=True, reason=None,
        filings=filings, insider_count=insider,
        insider_recent_count=insider_recent, truncated=truncated,
    )


def fetch_filings(
    tickers: list[str],
    *,
    days: int = 180,
    insider_days: int = 90,
    limit_per_ticker: int = 200,
    timeout: float = 15.0,
    # SEC 는 초당 10건을 넘기지 말라고 안내한다. 보유 종목은 20개 안쪽이라
    # 4 병렬이면 넉넉히 그 아래다.
    max_workers: int = 4,
) -> list[TickerFilings]:
    """보유 종목의 공시. ETF 처럼 CIK 가 없는 종목은 `reason` 을 달아 돌려준다."""
    wanted = [t.upper() for t in dict.fromkeys(tickers) if t]
    if not wanted:
        return []

    cik_map = fetch_cik_map(timeout=timeout)
    if not cik_map:
        # ⚠️여기서 빈 목록을 주면 화면이 "공시가 없다"고 말하게 된다.
        return [
            TickerFilings(
                ticker=t, cik=None, company=None, ok=False,
                reason="SEC 종목 목록을 받지 못했습니다",
            )
            for t in wanted
        ]

    today = date.today()
    since = today - timedelta(days=days)
    insider_since = today - timedelta(days=insider_days)
    # 최근 1/3 구간. 90일이면 30일이다 — 같은 창을 셋으로 나눠 "몰렸나"를 본다.
    insider_recent_since = today - timedelta(days=max(insider_days // 3, 1))

    known = [(t, *cik_map[t]) for t in wanted if t in cik_map]
    unknown = [
        TickerFilings(
            ticker=t, cik=None, company=None, ok=True,
            # ETF 는 신탁 단위로 공시한다 — 조회 실패가 아니라 대상이 아니다.
            reason="SEC 개별 공시 대상이 아닙니다 (ETF 등)",
        )
        for t in wanted
        if t not in cik_map
    ]

    results: list[TickerFilings] = []
    if known:
        with _client(timeout) as client:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                results = list(
                    pool.map(
                        lambda args: _one(
                            client, args[0], args[1], args[2],
                            since, insider_since, insider_recent_since,
                            limit_per_ticker,
                        ),
                        known,
                    )
                )
    return results + unknown
