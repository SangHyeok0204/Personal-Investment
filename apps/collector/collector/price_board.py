"""[가격 모니터] — 주간가격모니터 price_monitor.xlsx 판독 (2026-08-28).

[종목 모니터] 가운데 2~4번째 칸 카드의 데이터원. 84개 시장(주식 42·채권 17·원자재
14·환 5·암호화폐 6)의 DtD·WtD·MtD·YtD 와 3년 주간 시계열을 자산군 단위로 낸다.

★★분류·라벨·지표 계산식은 **회의자료 생성기에서 그대로 이식**했다
  (`S:\\GE\\raw\\리서치\\종합\\주간가격모니터\\output\\dashboard_html_writer.py`).
  같은 워크북을 두 소비자가 다르게 해석하면 회의자료와 대시보드 숫자가 갈린다.
  아래 상수는 그쪽 `_EQUITY_ROWS`·`_BOND_DISPLAY`·`_*_ROW_ORDER`·`_CSV_COL` 의 사본이다.
  ⚠️생성기 쪽이 바뀌면 여기도 같이 고쳐야 한다(import 할 수 없는 위치라 복사본이다).

★★지표 정의가 직관과 다른 곳이 세 군데다. 전부 생성기가 버그를 겪고 고친 자리다:
  1. **DtD 는 단순 전일 대비가 아니다.** 시트가 주말·휴일을 forward-fill 하므로
     값이 **실제로 달라지는** 직전 행까지 최대 7일 거슬러 올라간다.
  2. **MtD·YtD 는 리포트 날짜가 아니라 그 열 자신의 최신 관측일에 앵커한다.**
     안 지키면 갱신이 하루 밀린 열에서 "전 시장 MtD 0.00%" 가 나온다.
  3. **채권 17종은 bp** — 금리의 %변화율은 의미가 없고 마이너스 구간에서 부호가 뒤집힌다.

★★2026-08-31 소비 방식 개편(사용자 지시). 위 4개 지표는 **표(우하단 카드)로만** 간다
  — 롤링 1M·3M·6M·1Y 를 곁들여서. 차트는 달력 앵커 지표를 그리지 않는다(월초·연초
  리셋 톱니라 추세가 안 읽힌다). 자세한 갈래는 CHART_MODES 주석 참조.
"""
from __future__ import annotations

import io
import os
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

SRC_PATH = os.environ.get(
    "PRICE_BOARD_XLSX", "/srv/legacy/price_monitor/price_monitor.xlsx"
)
SHEET = "data"
HEADER_ROW = 1   # 1행 = 블룸버그 티커
DATA_ROW = 3     # 2행은 BDH 배열 수식(#REF!) 자리 — 실데이터는 3행부터
SERIES_YEARS = 3  # 차트 구간

# ── 자산군 정의 ──────────────────────────────────────────────────────────────
# (layer1, layer2, 표시명, 보조라벨, 티커). 비면 "" — 그 계층을 건너뛴다.
#   layer1 = 벤치마크/DM/EM · 미국/한국/… · 에너지/귀금속/…
#   layer2 = DM·EM 안의 지역 묶음(사용자 지시 2026-08-28). 벤치마크는 layer2 없이 바로 지수.
_EQUITY: list[tuple] = [
    ("벤치마크", "", "MSCI ACWI", "전세계", "MXWD Index"),
    ("벤치마크", "", "MSCI World", "선진", "MXWO Index"),
    ("벤치마크", "", "MSCI EM", "신흥", "MXEF Index"),
    ("DM", "미국", "S&P500", "", "SPX Index"),
    ("DM", "미국", "나스닥종합", "", "CCMP Index"),
    ("DM", "미국", "나스닥100", "", "NDX Index"),
    ("DM", "미국", "다우존스", "", "INDU Index"),
    ("DM", "미국", "러셀2000", "", "RTY Index"),
    ("DM", "미국", "필라델피아 반도체", "", "SOX Index"),
    ("DM", "유럽", "유로존 MSCI", "", "MXEU Index"),
    ("DM", "유럽", "STOXX600", "", "SXXP Index"),
    ("DM", "유럽", "유로 STOXX50", "", "SX5E Index"),
    ("DM", "유럽", "영국 FTSE100", "", "UKX Index"),
    ("DM", "유럽", "독일 DAX", "", "DAX Index"),
    ("DM", "유럽", "프랑스 CAC40", "", "CAC Index"),
    ("DM", "유럽", "스위스 SMI", "", "SMI Index"),
    ("DM", "유럽", "네덜란드 AEX", "", "AEX Index"),
    ("DM", "유럽", "스웨덴 OMX30", "", "OMX Index"),
    ("DM", "유럽", "이탈리아 FTSE MIB", "", "FTSEMIB Index"),
    ("DM", "유럽", "스페인 IBEX35", "", "IBEX Index"),
    ("DM", "일본·싱가포르", "닛케이225", "", "NKY Index"),
    ("DM", "일본·싱가포르", "TOPIX", "", "TPX Index"),
    ("DM", "일본·싱가포르", "싱가포르 STI", "", "STI Index"),
    ("DM", "그외", "캐나다 TSX", "", "SPTSX Index"),
    ("DM", "그외", "호주 ASX200", "", "AS51 Index"),
    # ★홍콩은 MSCI 상 DM 이지만 실질 노출이 중국이라 EM 에 둔다(생성기와 같은 판단).
    ("EM", "한국", "KOSPI200", "", "KOSPI2 Index"),
    ("EM", "한국", "KOSDAQ150", "", "KOSDQ150 Index"),
    ("EM", "한국", "KRX300", "", "KRX300 Index"),
    ("EM", "중국", "CSI300", "", "SHSZ300 Index"),
    ("EM", "중국", "상해종합", "", "SHCOMP Index"),
    ("EM", "중국", "과창판50", "", "STAR50 Index"),
    ("EM", "중국", "창업판", "", "SZ399006 Index"),
    ("EM", "중국", "H주 (HSCEI)", "", "HSCEI Index"),
    ("EM", "홍콩", "항셍", "", "HSI Index"),
    ("EM", "홍콩", "항셍테크", "", "HSTECH Index"),
    ("EM", "그외", "대만 가권", "", "TWSE Index"),
    ("EM", "그외", "인도 NIFTY50", "", "NIFTY Index"),
    ("EM", "그외", "베트남 VN", "", "VNINDEX Index"),
    ("EM", "그외", "인도네시아 JCI", "", "JCI Index"),
    ("EM", "그외", "사우디 TASI", "", "SASEIDX Index"),
    ("EM", "그외", "브라질 IBOV", "", "IBOV Index"),
    ("EM", "그외", "멕시코 IPC", "", "MEXBOL Index"),
]

_BOND: list[tuple] = [
    ("미국", "", "3M", "미국채", "GB3 Govt"),
    ("미국", "", "2Y", "미국채", "GT2 Govt"),
    ("미국", "", "5Y", "미국채", "GT5 Govt"),
    ("미국", "", "10Y", "미국채", "GT10 Govt"),
    ("미국", "", "30Y", "미국채", "GT30 Govt"),
    ("한국", "", "2Y", "국고채", "GTKRW2Y Govt"),
    ("한국", "", "3Y", "국고채", "GTKRW3Y Govt"),
    ("한국", "", "5Y", "국고채", "GTKRW5Y Govt"),
    ("한국", "", "10Y", "국고채", "GTKRW10Y Govt"),
    ("일본", "", "2Y", "일본국채", "GTJPY2Y Govt"),
    ("일본", "", "5Y", "일본국채", "GTJPY5Y Govt"),
    ("일본", "", "10Y", "일본국채", "GTJPY10Y Govt"),
    ("일본", "", "30Y", "일본국채", "GTJPY30Y Govt"),
    ("중국", "", "2Y", "중국국채", "GTCNY2Y Govt"),
    ("중국", "", "5Y", "중국국채", "GTCNY5Y Govt"),
    ("중국", "", "10Y", "중국국채", "GTCNY10Y Govt"),
    ("중국", "", "30Y", "중국국채", "GTCNY30Y Govt"),
]

# 원자재는 에너지 → 귀금속 → 산업금속 → 벤치마크 순(생성기와 같은 묶음).
# ★탄산리튬은 2026-08-28 신설 열 — 블벅 새로고침 전까지 값이 비어 행이 빠진다.
_COMMODITY: list[tuple] = [
    ("에너지", "", "WTI", "근월 (USD/bbl)", "CL1 COMB Comdty"),
    ("에너지", "", "브렌트", "근월 (USD/bbl)", "CO1 COMB Comdty"),
    ("에너지", "", "천연가스", "근월 (USD/MMBtu)", "NG1 COMB Comdty"),
    ("에너지", "", "우라늄", "Sprott 신탁", "U-U CN Equity"),
    ("귀금속", "", "금", "XAU (USD/oz)", "XAU Curncy"),
    ("귀금속", "", "은", "XAG (USD/oz)", "XAG Curncy"),
    ("귀금속", "", "백금", "XPT (USD/oz)", "XPT Curncy"),
    ("귀금속", "", "팔라듐", "XPD (USD/oz)", "XPD Curncy"),
    ("산업금속", "", "구리", "LME 3M (USD/t)", "LMCADS03 Comdty"),
    ("산업금속", "", "알루미늄", "LME 3M (USD/t)", "LMAHDS03 Comdty"),
    ("산업금속", "", "니켈", "LME 3M (USD/t)", "LMNIDS03 Comdty"),
    ("산업금속", "", "아연", "LME 3M (USD/t)", "LMZSDS03 Comdty"),
    ("산업금속", "", "철광석", "스왑 근월 (USD/t)", "SCO1 Comdty"),
    ("산업금속", "", "탄산리튬", "99.5% SMM", "L4CNVTTG SMMC Index"),
    ("벤치마크", "", "원자재지수", "BCOM", "BCOM Index"),
]

_FX: list[tuple] = [
    ("", "", "DXY", "달러인덱스", "DXY Curncy"),
    ("", "", "USDKRW", "달러/원", "USDKRW BGN Curncy"),
    ("", "", "EURKRW", "유로/원", "EURKRW BGN Curncy"),
    ("", "", "JPYKRW", "엔/원", "JPYKRW BGN Curncy"),
    ("", "", "USDJPY", "엔/달러 · 하락 = 엔 강세", "USDJPY BGN Curncy"),
]

_CRYPTO: list[tuple] = [
    ("", "", "BTC", "USD", "XBTUSD BGN Curncy"),
    ("", "", "ETH", "USD", "XETUSD BGN Curncy"),
    ("", "", "SOL", "USD", "XSOUSD BGN Curncy"),
    ("", "", "XRP", "USD", "XRPUSD BGN Curncy"),
    ("", "", "크립토지수", "BGCI", "BGCI Index"),
    ("", "", "비트코인ETF", "IBIT", "IBIT US Equity"),
]

CATEGORIES: list[dict] = [
    {"key": "equity", "label": "주식", "rows": _EQUITY, "yield": False},
    {"key": "bond", "label": "채권", "rows": _BOND, "yield": True},
    {"key": "commodity", "label": "원자재", "rows": _COMMODITY, "yield": False},
    {"key": "fx", "label": "환", "rows": _FX, "yield": False},
    {"key": "crypto", "label": "비트코인", "rows": _CRYPTO, "yield": False},
]
_BY_KEY = {c["key"]: c for c in CATEGORIES}
DEFAULT_CAT = "equity"


# ── 지표 계산 (순수 — 테스트는 여기를 겨눈다) ───────────────────────────────

def _asof(series: dict[date, float], upto: date) -> date | None:
    """그 열이 실제로 값을 가진 마지막 날(≤ upto)."""
    ds = [d for d in series if d <= upto]
    return max(ds) if ds else None


def _dtd_ref(series: dict[date, float], today: date) -> date | None:
    """DtD 기준일 — 값이 **실제로 달라지는** 직전 관측일. 최대 7일 거슬러 간다.

    시트가 주말·휴일을 forward-fill 하므로 단순 t-1 은 0.00% 만 낸다."""
    cur = series.get(today)
    if cur is None:
        return None
    d = today - timedelta(days=1)
    limit = today - timedelta(days=7)
    while d >= limit:
        v = series.get(d)
        if v is not None and v != cur:
            return d
        d -= timedelta(days=1)
    return None


def _at_or_before(series: dict[date, float], target: date) -> float | None:
    ds = [d for d in series if d <= target]
    return series[max(ds)] if ds else None


def _change(cur: float, ref: float | None, is_yield: bool) -> float | None:
    """금리는 bp 변화폭, 그 외는 % 수익률."""
    if ref is None:
        return None
    if is_yield:
        return (cur - ref) * 100.0
    if ref == 0:
        return None
    return (cur / ref - 1.0) * 100.0


# ── 롤링 창 (요약 표 전용) ───────────────────────────────────────────────────
# ★2026-08-31 사용자 지시로 신설. 달력 앵커(MtD·YtD)는 월초·연초에 **모든 시장이
#   0 근처로 뭉쳐** 비교가 안 된다 — 8월 3일의 MtD 로 섹터를 고르는 건 이틀치를
#   고르는 것이다. 앵커가 t 를 따라 미끄러지는 롤링 창을 같이 내서, 언제 봐도 같은
#   길이의 성과를 비교할 수 있게 한다.
# ★일수는 **달력 기준**이다. 거래일로 세려면 ffill 행을 걷어내야 하는데, 그 판정
#   ("값이 직전과 같으면 휴일")이 금리처럼 자릿수 짧은 열에서 오탐한다. 시트가 주말을
#   ffill 하므로 달력 창의 기준일은 항상 값이 있다 — 굳이 거래일로 셀 이유가 없다.
ROLLING = [("r1m", "1M", 30), ("r3m", "3M", 91), ("r6m", "6M", 182), ("r1y", "1Y", 365)]


def compute_row(series: dict[date, float], upto: date, is_yield: bool) -> dict | None:
    """한 시장의 Price·DtD·WtD·MtD·YtD + 롤링 1M·3M·6M·1Y. 값이 없으면 None."""
    a = _asof(series, upto)
    if a is None:
        return None
    cur = series[a]
    dref = _dtd_ref(series, a)
    out = {
        "asof": a.isoformat(),
        "price": cur,
        # ★MtD·YtD 는 리포트 날짜가 아니라 이 열 자신의 최신일(a)에 앵커한다.
        "dtd": _change(cur, series.get(dref) if dref else None, is_yield),
        "wtd": _change(cur, _at_or_before(series, a - timedelta(days=7)), is_yield),
        "mtd": _change(cur, _at_or_before(series, a.replace(day=1) - timedelta(days=1)), is_yield),
        "ytd": _change(cur, _at_or_before(series, date(a.year - 1, 12, 31)), is_yield),
    }
    for key, _label, days in ROLLING:
        out[key] = _change(cur, _at_or_before(series, a - timedelta(days=days)), is_yield)
    return out


def _weekly(series: dict[date, float], since: date) -> list[list]:
    """주(월요일 기준) 마지막 관측치. 일별 1,400점을 ~156점으로 줄인다."""
    keep: dict[tuple[int, int], tuple[date, float]] = {}
    for d, v in series.items():
        if d < since:
            continue
        iso = d.isocalendar()
        prev = keep.get((iso[0], iso[1]))
        if prev is None or d > prev[0]:
            keep[(iso[0], iso[1])] = (d, v)
    return [[d.isoformat(), v] for d, v in sorted(keep.values())]


def build_payload(columns: dict[str, dict[date, float]], cat_key: str) -> dict:
    """{티커: {날짜: 값}} + 자산군 키 → 카드 payload."""
    cat = _BY_KEY.get(cat_key) or _BY_KEY[DEFAULT_CAT]
    is_yield = cat["yield"]
    upto = max((d for s in columns.values() for d in s), default=None)

    out: dict = {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "note": None,
        "cat": cat["key"],
        "cat_label": cat["label"],
        "unit": "bp" if is_yield else "%",
        "is_yield": is_yield,
        "asof": None,
        "categories": [{"key": c["key"], "label": c["label"]} for c in CATEGORIES],
        "rows": [],
        "tree": [],
        "series": [],
    }
    if upto is None:
        return out

    since = date(upto.year - SERIES_YEARS, upto.month, min(upto.day, 28))
    for l1, l2, label, sub, ticker in cat["rows"]:
        s = columns.get(ticker)
        if not s:
            continue  # 시트에 없는 열(신설 직후 등)은 조용히 빠진다
        r = compute_row(s, upto, is_yield)
        if r is None:
            continue
        key = ticker  # 티커가 곧 고유키다(표시명은 중복 가능)
        out["rows"].append({"key": key, "group": l1, "sub_group": l2,
                            "label": label, "sub": sub, **r})
        out["series"].append({"key": key, "label": label, "points": _weekly(s, since)})

    out["tree"] = _build_tree(out["rows"])
    out["asof"] = max((r["asof"] for r in out["rows"]), default=None)
    return out


def _build_tree(rows: list[dict]) -> list[dict]:
    """평면 rows → layer1/layer2 중첩. 그룹이 빈 문자열이면 그 계층을 건너뛴다.

    행 순서를 그대로 따라간다 — 분류 순서가 곧 표시 순서라 정렬하지 않는다
    (벤치마크→DM→EM, 만기 오름차순 등은 이미 상수에서 정해져 있다)."""
    tree: list[dict] = []
    by_l1: dict[str, dict] = {}
    by_l2: dict[tuple[str, str], dict] = {}
    for r in rows:
        leaf = {k: v for k, v in r.items() if k not in ("group", "sub_group")}
        l1, l2 = r["group"], r["sub_group"]
        if not l1:
            tree.append({"type": "leaf", **leaf})
            continue
        node1 = by_l1.get(l1)
        if node1 is None:
            node1 = {"type": "node", "label": l1, "children": []}
            by_l1[l1] = node1
            tree.append(node1)
        if not l2:
            node1["children"].append({"type": "leaf", **leaf})
            continue
        node2 = by_l2.get((l1, l2))
        if node2 is None:
            node2 = {"type": "node", "label": l2, "children": []}
            by_l2[(l1, l2)] = node2
            node1["children"].append(node2)
        node2["children"].append({"type": "leaf", **leaf})
    return tree


# ── 지표 시계열 (차트용) ─────────────────────────────────────────────────────

# ★★2026-08-31 전면 교체(사용자 지시). DtD·WtD·MtD·YtD **시계열**을 전부 뺐다 —
#   달력 앵커 지표는 월초·연초마다 0 으로 리셋되는 톱니라 추세를 읽을 수 없고, 그
#   숫자는 우하단 요약 표(compute_row 의 8개 값)가 이미 보여준다. 차트는 3모드만:
#     · cum (누적수익률)    — 보는 구간 시작 = 0% 로 리베이스. **프론트가 계산한다**.
#     · rs  (벤치마크 대비) — 같은 가격 계열을 벤치마크로 나눈 상대곡선. 역시 프론트.
#     · r3m (롤링 3M)       — 구간과 무관하므로 **서버가 계산**해 내려보낸다.
# ★★cum·rs 를 서버가 계산하면 안 되는 이유: 리베이스 기준점은 사용자가 헤더 날짜
#   칸으로 좁힌 **보는 구간의 첫 점**이다. 서버는 그 구간을 모르므로 고정 시작점으로
#   계산할 수밖에 없고, 그러면 구간을 좁혀도 0% 기준이 안 따라온다. 그래서 서버는
#   **가격 원본(price)** 을 실어 주고 프론트가 나눈다 — 모드 전환에 재요청도 없다.
CHART_MODES = [
    {"key": "cum", "label": "누적수익률"},
    {"key": "rs", "label": "벤치마크 대비"},
    {"key": "r3m", "label": "롤링 3M"},
]

# 차트의 롤링 창은 표의 3M 과 **같은 창**을 쓴다 — 한 화면에서 같은 이름이 다른 값을
# 말하면 안 된다. ROLLING 에서 끌어와 두 곳이 갈라지지 않게 한다.
R3M_DAYS = dict((k, d) for k, _l, d in ROLLING)["r3m"]

# 자산군별 벤치마크 — 상대곡선(rs)의 분모다. 각 자산군 '벤치마크' 묶음의 첫 행.
# ★채권·환에는 없다: 금리를 금리로 나눈 상대곡선은 의미가 없고(bp 세계에는 비율이
#   없다), 환은 자산군 자체가 이미 상대가격이라 분모를 세울 자리가 없다.
#   payload 의 benchmark 가 null 이면 화면이 그 토글을 비활성으로 둔다.
BENCHMARK = {
    "equity": "MXWD Index",     # MSCI ACWI (전세계)
    "commodity": "BCOM Index",  # 원자재지수
    "crypto": "BGCI Index",     # 크립토지수
}


def compute_rolling_series(
    series: dict[date, float], days: int, is_yield: bool
) -> list[list]:
    """날짜마다 '그 시점의 N일 전 대비'를 계산해 한 시계열로 낸다(주간 솎기 포함).

    ★"2026-04-01 의 롤링 3M" 은 그날 기준으로 다시 계산한 값이다 — 최신 한 점이
      아니라 **매일의 지표를 역사적으로** 쌓는다. 0 선 교차가 곧 추세 전환이다.

    ★기준값 조회는 이분탐색이다(2026-08-28). `_at_or_before` 는 호출마다 전체 날짜를
      훑어 O(n²) 이 되는데, 그룹 차트가 한 요청에 시장 11개를 계산하면서 실측 1초/시장
      → 11초가 됐다. 정렬된 날짜 배열 하나를 만들어 두고 bisect 로 찍는다(결과 동일).
    """
    ds = sorted(series)
    vs = [series[d] for d in ds]

    def at_or_before(target: date) -> float | None:
        i = bisect_right(ds, target) - 1
        return vs[i] if i >= 0 else None

    out: dict[date, float] = {}
    for d in ds:
        v = _change(series[d], at_or_before(d - timedelta(days=days)), is_yield)
        if v is not None:
            out[d] = v
    return _weekly(out, min(out)) if out else []


def _chart_series(ticker: str, label: str, sub: str, s: dict[date, float],
                  is_yield: bool) -> dict:
    """차트 계열 한 개 — 가격 원본 + 롤링 3M 을 같이 싣는다.

    ★두 배열의 날짜가 어긋나면 안 된다. 둘 다 `_weekly`(ISO 주 마지막 관측일)를
      거치므로 같은 날짜에 떨어진다 — r3m 만 앞 91일이 없어 짧게 시작할 뿐이다.
    """
    return {
        "key": ticker,
        "label": label,
        "sub": sub,
        "price": _weekly(s, min(s)),
        "r3m": compute_rolling_series(s, R3M_DAYS, is_yield),
    }


def _benchmark_block(columns: dict[str, dict[date, float]], cat: dict) -> dict | None:
    """상대곡선의 분모가 될 벤치마크 가격 계열. 없는 자산군이면 None."""
    ticker = BENCHMARK.get(cat["key"])
    if not ticker:
        return None
    s = columns.get(ticker)
    if not s:
        return None
    label = next((r[2] for r in cat["rows"] if r[4] == ticker), ticker)
    return {"key": ticker, "label": label, "points": _weekly(s, min(s))}


def build_metric_payload(columns: dict[str, dict[date, float]], key: str) -> dict:
    """티커 하나의 지표 시계열 payload. 어느 자산군인지도 같이 찾아 단위를 정한다."""
    spec = None
    for c in CATEGORIES:
        for l1, l2, label, sub, ticker in c["rows"]:
            if ticker == key:
                spec = (c, label, sub)
                break
        if spec:
            break

    out: dict = {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "key": key,
        "label": spec[1] if spec else key,
        "sub": spec[2] if spec else "",
        "cat": spec[0]["key"] if spec else None,
        "unit": "bp" if (spec and spec[0]["yield"]) else "%",
        "is_yield": bool(spec and spec[0]["yield"]),
        "modes": [dict(m) for m in CHART_MODES],
        "series": [],
        "benchmark": None,
        "note": None,
    }
    s = columns.get(key)
    if not spec or not s:
        out["note"] = f"시트에 없는 시장입니다 — {key}"
        return out

    out["series"].append(_chart_series(key, spec[1], spec[2], s, out["is_yield"]))
    out["benchmark"] = _benchmark_block(columns, spec[0])
    last = max(s)
    out["asof"] = last.isoformat()
    out["price"] = s[last]
    return out


def build_group_metric_payload(
    columns: dict[str, dict[date, float]],
    cat_key: str,
    l1: str,
    l2: str,
) -> dict:
    """한 묶음(예: DM/미국)에 속한 시장들의 차트 계열을 한 번에 낸다.

    ★단일 시장 payload 와 **모양이 같다** — 계열이 1개냐 N개냐만 다르다. 그래서
      차트는 series 배열 하나만 그리면 양쪽을 다 그린다.
    ★2026-08-31: 지표를 골라 받던 `metric` 파라미터가 없어졌다. 이제 계열마다
      price·r3m 을 **둘 다** 싣기 때문에 모드를 바꿔도 재요청이 없다.
    """
    cat = _BY_KEY.get(cat_key) or _BY_KEY[DEFAULT_CAT]
    is_yield = cat["yield"]
    rows = [r for r in cat["rows"] if r[0] == l1 and r[1] == l2]

    out: dict = {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "kind": "group",
        "cat": cat["key"],
        "l1": l1,
        "l2": l2,
        "label": l2 or l1 or cat["label"],
        "sub": f"{cat['label']} · {len(rows)}개 시장",
        "modes": [dict(m) for m in CHART_MODES],
        "unit": "bp" if is_yield else "%",
        "is_yield": is_yield,
        "series": [],
        "benchmark": None,
        "asof": None,
        "note": None,
    }
    if not rows:
        out["note"] = f"분류에 없는 묶음입니다 — {cat_key}/{l1}/{l2}"
        return out

    asofs: list[str] = []
    for _l1, _l2, label, sub, ticker in rows:
        s = columns.get(ticker)
        if not s:
            continue  # 시트에 없는 열(신설 직후 등)은 조용히 빠진다
        out["series"].append(_chart_series(ticker, label, sub, s, is_yield))
        asofs.append(max(s).isoformat())

    out["benchmark"] = _benchmark_block(columns, cat)
    out["asof"] = max(asofs) if asofs else None
    if not out["series"]:
        out["note"] = "이 묶음은 아직 시트에 값이 없습니다."
    return out


# ── xlsx 판독 (mtime+size 캐시) ──────────────────────────────────────────────
_CACHE: dict = {"sig": None, "cols": None}


def _read_columns(path: str = SRC_PATH) -> dict[str, dict[date, float]]:
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    if _CACHE["sig"] == sig and _CACHE["cols"] is not None:
        return _CACHE["cols"]

    with open(path, "rb") as f:
        blob = f.read()
    try:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        ws = wb[SHEET]
        rows = ws.iter_rows(values_only=True)
        header = next(rows)
        # 2행(BDH 수식 자리)을 건너뛴다
        for _ in range(DATA_ROW - HEADER_ROW - 1):
            next(rows, None)
        idx = {str(h).strip(): i for i, h in enumerate(header) if h}
        cols: dict[str, dict[date, float]] = {t: {} for t in idx if t != "datetime"}
        for r in rows:
            d = r[0]
            if not isinstance(d, datetime):
                continue
            dd = d.date()
            for t, i in idx.items():
                if t == "datetime" or i >= len(r):
                    continue
                v = r[i]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    cols[t][dd] = float(v)
        wb.close()
    except Exception:
        if _CACHE["cols"] is not None:
            return _CACHE["cols"]
        raise

    _CACHE["sig"] = sig
    _CACHE["cols"] = cols
    return cols


def build_price_board(cat: str = DEFAULT_CAT) -> dict:
    """xlsx → 자산군 하나의 카드 payload. 원천 결측은 503 이 아니라 note 로 알린다."""
    try:
        cols = _read_columns()
    except FileNotFoundError:
        out = build_payload({}, cat)
        out["note"] = f"원천 파일이 없습니다 — {SRC_PATH}"
        return out
    return build_payload(cols, cat)


def build_metric_series(key: str) -> dict:
    """시장 하나의 차트 계열(가격 + 롤링 3M). 차트가 클릭할 때마다 하나씩 받아 간다."""
    try:
        cols = _read_columns()
    except FileNotFoundError:
        out = build_metric_payload({}, key)
        out["note"] = f"원천 파일이 없습니다 — {SRC_PATH}"
        return out
    return build_metric_payload(cols, key)


def build_group_series(cat: str, l1: str, l2: str = "") -> dict:
    """묶음 하나(예: DM/미국)의 시장별 차트 계열. 목록에서 그룹을 누를 때 받아 간다."""
    try:
        cols = _read_columns()
    except FileNotFoundError:
        out = build_group_metric_payload({}, cat, l1, l2)
        out["note"] = f"원천 파일이 없습니다 — {SRC_PATH}"
        return out
    return build_group_metric_payload(cols, cat, l1, l2)
