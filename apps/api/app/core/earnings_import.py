"""어닝모니터 엑셀(`보유종목정리.xlsx`) → 실적 표 이관용 파싱 (계획 B1).

원본은 엑셀이 정본이고 SQLite 는 미러였다(`earnings_store.mirror_master_to_db`). 옮기는 시트:
  - `실적`(현재) · `과거` — 한 행 = 한 종목의 최근 발표(+ 다음 예정일). 22열.
  - `관전포인트` — (티커, 분기, 순위, 포인트, 결과). 713행.
옮기지 않는 것: `종합`·`펀드목록`·`M2205`(회사 펀드 보유), `보유펀드` 열.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_SUFFIX = {"T": Decimal("1e12"), "B": Decimal("1e9"), "M": Decimal("1e6"), "K": Decimal("1e3")}
# 원본이 실패를 칸에 글자로 적어 둔 것(예: '[타임아웃] CLI 응답 500초 초과') — 내용이 아니다
_FAILURE = re.compile(r"^\s*\[(타임아웃|오류|실패|error|timeout)", re.I)
ALIASES = {"GOOG": "GOOGL"}


def norm_ticker(v) -> str:
    t = re.sub(r"\s+US(\s+EQUITY)?$", "", str(v or "").strip().upper()).strip()
    return ALIASES.get(t, t)


def parse_money(v) -> Decimal | None:
    """'108.86B' · '4.89T' · '815.6M' · 1.6 · '-0.84' → Decimal(달러). 못 읽으면 None."""
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s or s in ("-", "—", "N/A", "nan"):
        return None
    mult = Decimal(1)
    if s[-1].upper() in _SUFFIX:
        mult = _SUFFIX[s[-1].upper()]
        s = s[:-1]
    try:
        return Decimal(s) * mult
    except InvalidOperation:
        return None


def parse_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def parse_timing(v) -> str | None:
    s = str(v or "").strip().lower()
    if s.startswith("before") or s in ("bmo", "장전"):
        return "BMO"
    if s.startswith("after") or s in ("amc", "장후"):
        return "AMC"
    return None


def quarter_of(d: date | None) -> str | None:
    """원본 `derive_fiscal_quarter` — 발표 달로 보고 분기 라벨(1~3월 발표 = 전년 Q4). 회사 회계분기가 아니다."""
    if d is None:
        return None
    if d.month <= 3:
        return f"{d.year - 1}Q4"
    return f"{d.year}Q{(d.month - 1) // 3}"


def verdict(v) -> str | None:
    s = str(v or "").strip()
    return s if s in ("상회", "부합", "하회") else None


def text_or_none(v) -> str | None:
    s = str(v if v is not None else "").strip()
    # 원본 엑셀의 빈칸이 판다스를 거치며 'nan' 글자로 남아 있다(실측: 관전포인트 결과 칸 '→ nan')
    return None if not s or s.lower() in ("nan", "none", "null") or _FAILURE.match(s) else s


def surprise_pct(actual: Decimal | None, forecast: Decimal | None) -> Decimal | None:
    if actual is None or forecast is None or forecast == 0:
        return None
    return round((actual - forecast) / abs(forecast) * 100, 2)


def result_rows(header: tuple, rows: list[tuple], targets: set[str]) -> list[dict]:
    """`실적`/`과거` 시트 → [{event, result | None, points: [(rank, point, result)], upcoming}] (대상 종목만)."""
    ix = {h: i for i, h in enumerate(header) if h}
    g = lambda r, k: r[ix[k]] if k in ix and ix[k] < len(r) else None  # noqa: E731
    out = []
    for r in rows:
        tk = norm_ticker(g(r, "티커"))
        if tk not in targets:
            continue
        rd = parse_date(g(r, "최근실적발표일"))
        q = quarter_of(rd)
        if q is None:
            continue
        eps_f, rev_f = parse_money(g(r, "예상EPS")), parse_money(g(r, "예상매출"))
        eps_a, rev_a = parse_money(g(r, "결과EPS")), parse_money(g(r, "결과매출"))
        has_result = eps_a is not None or rev_a is not None or verdict(g(r, "컨센대비"))
        out.append({
            "event": {"ticker": tk, "quarter": q, "company": text_or_none(g(r, "기업명")), "report_date": rd,
                      "timing": parse_timing(g(r, "Before/After")), "eps_forecast": eps_f, "revenue_forecast": rev_f,
                      "revenue_forecast_status": "unverified" if rev_f is not None else None,
                      "revenue_forecast_source": "import" if rev_f is not None else None,
                      "market_cap": parse_money(g(r, "시가총액"))},
            # ⚠️서프라이즈 %는 계산하지 않는다 — 원본 `예상EPS/예상매출` 칸이 분기마다 갱신되지 않았다(실측: GOOGL · NVDA ·
            #   MSFT 의 Q1 · Q2 예상치가 똑같다, NBIS 예상 EPS −62.2). 그걸로 나누면 +216% · −4,767% 같은 값이 나온다.
            #   원본 판정(`컨센대비`)만 '원본 판정'으로 옮기고, 실제 서프라이즈는 Nasdaq 이력(B3a)이 채운다.
            "result": {"eps_actual": eps_a, "revenue_actual": rev_a, "verdict": verdict(g(r, "컨센대비")),
                       "eps_surprise_pct": None, "revenue_surprise_pct": None,
                       "reaction_note": text_or_none(g(r, "기타시장반응")),
                       "detail": {"import": "어닝모니터 엑셀", "verdict_source": "원본 판정(컨센대비 칸)",
                                  "forecast_unverified": True}} if has_result else None,
            "points": [(i, text_or_none(g(r, f"관전포인트{i}")), text_or_none(g(r, f"관전포인트결과{i}")))
                       for i in range(1, 5)],
            "upcoming": parse_date(g(r, "예정실적발표일")),
        })
    return out


def watchpoint_rows(rows: list[tuple], targets: set[str]) -> list[dict]:
    """`관전포인트` 시트(티커, 분기, 순위, 포인트, 결과) → 대상 종목만. 실패 문구 칸은 비운다."""
    out = []
    for r in rows:
        if len(r) < 4:
            continue
        tk = norm_ticker(r[0])
        q = str(r[1] or "").strip()
        try:
            rank = int(str(r[2]).strip())
        except ValueError:
            continue
        if tk not in targets or not re.fullmatch(r"\d{4}Q[1-4]", q) or not 1 <= rank <= 4:
            continue
        point = text_or_none(r[3])
        result = text_or_none(r[4] if len(r) > 4 else None)
        if point or result:
            out.append({"ticker": tk, "quarter": q, "rank": rank, "point": point, "result": result})
    return out
