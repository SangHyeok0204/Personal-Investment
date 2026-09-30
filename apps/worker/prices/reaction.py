"""실적 발표 후 주가 반응 — 토스 1분봉, 세션 고정 구간 (계획 B4) — 원본 `toss_prices.py` 이식.

구간(원본 규약 — 발표 시각은 공개 소스로 믿을 만하게 못 얻는다, 8-K 접수시각은 1분~5시간 편차):
  AMC(장후)  당일 16:00 ET 종가 → 당일 17:30 ET (90분)
  BMO(장전)  전일 16:00 ET 종가 → 당일 08:30 ET (개장 1시간 전)
  원본 실측(2026-08): AMC 44건 98% 가 마감 +30분 안에 반응 시작, BMO 35건 전부 08:30 안.
★시각을 모르면(Nasdaq '미정') **값을 내지 않는다** — 장전 발표를 장후로 넘겨짚으면 발표와 무관한 구간을 재서
  크래시도 경고도 없이 틀린 숫자가 나간다(원본 주석).
★'구간이 끝났나'는 봉의 신선도가 아니라 **벽시계**로 — 거래 드문 종목은 17:25 이후 체결이 없는 게 정상(원본 실측 HEI).
★토스 토큰은 클라이언트당 1개 — API 시세 캐시와 같은 키다. 정규장 중에는 API 가 토스를 먼저 쓰므로
  이 계산은 **정규장이 닫혀 있을 때만** 한다(부르는 쪽에서 `us_regular_session_open` 으로 막는다).
봉 라벨 = 봉 **종료**시각(원본 실측). 토스는 30일 전 장후 1분봉도 준다(계획 실측) → 캐치업 가능.
전일 휴장이어도 괜찮다 — 기준 시각 **이전** 봉을 받으므로 그 전 마지막 세션 종가가 잡힌다.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
KST = timezone(timedelta(hours=9))
SESSIONS = {
    "AMC": {"base": time(16, 0), "end": time(17, 30), "base_prev_day": False, "label": "장후 16:00→17:30 ET"},
    "BMO": {"base": time(16, 0), "end": time(8, 30), "base_prev_day": True, "label": "전일 16:00→08:30 ET"},
}


def prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def session_window(day: date, timing: str | None) -> tuple[datetime, datetime, str] | None:
    """(기준 시각, 끝 시각, 라벨) ET. 장전/장후를 모르면 None."""
    spec = SESSIONS.get((timing or "").upper())
    if not spec:
        return None
    base_day = prev_weekday(day) if spec["base_prev_day"] else day
    return (datetime.combine(base_day, spec["base"], tzinfo=ET), datetime.combine(day, spec["end"], tzinfo=ET),
            spec["label"])


def us_regular_session_open(now: datetime | None = None) -> bool:
    et = (now or datetime.now(timezone.utc)).astimezone(ET)
    return et.weekday() < 5 and 9 * 60 + 30 <= et.hour * 60 + et.minute < 16 * 60


def parse_bars(candles) -> list[dict]:
    """토스 candles → [{dt(aware), close}] 오름차순. 깨진 봉은 버린다."""
    out = []
    for c in candles or []:
        try:
            dt = datetime.fromisoformat(c["timestamp"])
            close = float(c["closePrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        out.append({"dt": dt, "close": close})
    return sorted(out, key=lambda b: b["dt"])


def close_at_or_before(bars: list[dict], when: datetime) -> dict | None:
    got = [b for b in bars if b["dt"] <= when]
    return got[-1] if got else None


def compute(base_bar, end_bar, end_at: datetime, now: datetime | None = None) -> float | None:
    if not base_bar or not end_bar or not base_bar["close"] or end_bar["dt"] <= base_bar["dt"]:
        return None
    if (now or datetime.now(timezone.utc)) < end_at:
        return None                                   # 구간이 아직 안 끝났다
    return round((end_bar["close"] - base_bar["close"]) / base_bar["close"] * 100, 1)


def toss_symbol(ticker: str) -> str:
    """BRK/B · BRK-B → BRK.B(원본 실측: 토스 클래스 구분자는 '.'). 그 밖은 그대로."""
    t = ticker.strip().upper().replace("/", ".")
    return re.sub(r"^([A-Z]+)-([A-Z])$", r"\1.\2", t)


def earnings_reaction(toss, ticker: str, day: date, timing: str | None, now: datetime | None = None) -> dict | None:
    """→ {pct, window, base_price, end_price} 또는 None(시각 모름 · 구간 안 끝남 · 봉 없음)."""
    w = session_window(day, timing)
    if not w:
        return None
    base_at, end_at, label = w
    if (now or datetime.now(timezone.utc)) < end_at:
        return None

    def bars(before: datetime) -> list[dict]:
        res = toss._get("/api/v1/candles", {"symbol": toss_symbol(ticker), "interval": "1m", "count": 200,
                                            "before": before.astimezone(KST).isoformat()})
        return parse_bars((res or {}).get("candles"))

    end_bars = bars(end_at)
    # AMC 는 90분이라 200봉 한 번에 기준가까지 들어온다. BMO 는 16시간이라 따로(원본).
    base_bars = end_bars if (timing or "").upper() == "AMC" else bars(base_at)
    b, e = close_at_or_before(base_bars, base_at), close_at_or_before(end_bars, end_at)
    pct = compute(b, e, end_at, now)
    if pct is None:
        return None
    return {"pct": pct, "window": label, "base_price": b["close"], "end_price": e["close"]}
