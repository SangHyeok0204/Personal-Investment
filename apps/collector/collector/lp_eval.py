"""LP 평가 — 인정 스프레드 틱 체류시간(분) 누적 (2026-07-27).

목적: LP 들이 각 ETF 마다 호가/물량을 잘 깔고 있는가? CHECK 호가에서 ACE 9종의
'인정 스프레드'(매도·매수 각각 최우선호가부터 처음 1,000주 이상 실린 틱까지의
가격차를 틱으로 환산 — 프론트 화면 알림과 동일 정의)를 60초마다 표본해, 각 틱값
에서 보낸 시간(분)을 trade_date·기준(basis)·틱별로 SQLite 에 누적한다. 하루 장이
돌면 ETF 별 스프레드-틱 분포가 쌓이고, /lp-eval 이 히스토그램+평균·최빈·중앙값을 준다.

기준(basis) 2종을 함께 쌓는다 (나중에 어느 쪽이 'LP 평가'에 맞는지 고를 수 있게):
  · 'lp'    : LP 물량(lpAskQtys/lpBidQtys) 기준 — 리테일이 안 섞여 LP 성실도에 맞음.
  · 'total' : 총호가(askQtys/bidQtys) 기준 — 화면 알림 전광판과 동일(리테일 포함).

버킷(tick):
  · -1 = '없음'(none) : 5틱 안에 한쪽이라도 1,000주↑ 인정호가 부재 = 최악.
  ·  0 = '정상'(ok)   : 인정 스프레드 < 3틱(알림 미발화 구간, 분모용 컨텍스트).
  · ≥3 = 알림틱       : 인정 스프레드가 그 틱(3,4,5,…). 화면 알림이 뜨는 값.

프론트 lib/hoga.ts 의 recognizedSpreadTicks/recognizedQuotePrice/tickSize 를 그대로
이식한다(값 일치 보장). 순수 판독·누적 — 예외는 삼키고 그 표본만 건너뛴다.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collector.legacy_inputs import CACHE_DIR, ensure_dirs

_KST = timezone(timedelta(hours=9))
DB_PATH = CACHE_DIR / "lp_eval.db"

# 일별 LP 평가 산출물 출력 폴더 — collector 가 S: RW 마운트(/srv/lp_eval)로 받는다
# (호스트 S:\GE\raw\data\ETF_iNAV모니터\lp_eval). 폴더가 없으면(로컬 개발·마운트
# 부재) 저장을 조용히 건너뛴다. (2026-07-27 사용자 요청: 일별 통계를 S: 에 보관)
LP_EVAL_OUT_DIR = Path(os.environ.get("COLLECTOR_LP_EVAL_DIR", "/srv/lp_eval"))

# 프론트 lib/hoga.ts 상수와 일치.
RECOGNIZED_QTY_MIN = 1_000
# 심각도 밴드 경계 — 화면이 조건부 알림에서 상시 요약으로 바뀌며(2026-07-30) '발화
# 하한'이 사라지고 색 밴드만 남았다. 히스토그램의 '정상'은 옅은 회색 밴드(<20bp)에
# 해당한다. 구 SPREAD_ALERT_MIN_BP(15bp)·SPREAD_MISSING_MAX_TICKS(20틱)는 폐기.
SPREAD_WARN_BP = 20
SPREAD_CRIT_BP = 40
SPREAD_ALERT_MIN_TICKS = 3        # 체결가 없을 때만 쓰는 폴백

# ACE 모니터링 대상(현재 9종, 프론트 CARD_TICKER_ORDER 와 동일 집합·순서).
ACE_TICKERS = (
    "414270", "457480", "483320", "483330",
    "483340", "0079X0", "0118Z0", "0180V0", "0199C0",
)

# LP 평가 표본 구간 — KRX LP 호가 의무 시간대(09:05~15:20 KST). 개장 직후 5분
# (09:00~09:05)과 종가 단일가 구간(15:20~15:30)은 LP 의무가 면제·종료되므로 표본
# 하지 않는다 (2026-07-27 사용자 확정). CHECK 수신 지연이 크면(끊김) 그 분은 제외.
SESSION_START_MIN = 9 * 60 + 5      # 09:05
SESSION_END_MIN = 15 * 60 + 20      # 15:20
HOGA_FRESH_MAX_S = 15.0

_NONE_TICK = -1  # '없음' 센티넬
_OK_TICK = 0     # '정상'(<3틱) 센티넬


def _log(msg: str) -> None:
    print(f"[lp-eval] {msg}", file=sys.stderr, flush=True)


def _hhmm(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _tick_size(price: float) -> int:
    # KRX 국내 ETF 호가단위 — 2,000원 미만 1원, 이상 5원 (lib/hoga.ts tickSize).
    return 1 if price < 2000 else 5


def _to_num(v):
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def _ladder_prices(wide, narrow, side):
    """판정에 쓸 가격 사다리 — 10단(askPrices10/bidPrices10)이 오면 그걸, 없으면 5단.
    단조성이 깨지는 지점에서 자른다. (lib/hoga.ts ladderPrices 이식 — 사유는 그쪽 주석.)
    """
    src = wide if wide else (narrow or [])
    out = []
    for raw in src:
        p = _to_num(raw)
        if p is None or p <= 0:
            break
        if out and (p <= out[-1] if side == "ask" else p >= out[-1]):
            break
        out.append(p)
    return out


def _recognized_quote_price(prices, qtys):
    """최우선호가부터 바깥으로 훑어 처음 잔량 ≥ RECOGNIZED_QTY_MIN 인 호가의 가격.
    (lib/hoga.ts recognizedQuotePrice 이식.) 없으면 None."""
    if not prices or not qtys:
        return None
    for i in range(len(prices)):
        p = _to_num(prices[i])
        q = _to_num(qtys[i]) if i < len(qtys) else None
        if p is not None and p > 0 and q is not None and q >= RECOGNIZED_QTY_MIN:
            return p
    return None


def _recognized_spread_ticks(ask_prices, ask_qtys, bid_prices, bid_qtys):
    """(인정매도호가 − 인정매수호가) 를 틱으로 환산. 한쪽이라도 인정호가가 없으면
    None (= '없음'). lib/hoga.ts recognizedSpreadTicks 이식."""
    rec_ask = _recognized_quote_price(ask_prices, ask_qtys)
    rec_bid = _recognized_quote_price(bid_prices, bid_qtys)
    if rec_ask is None or rec_bid is None:
        return None
    tick = _tick_size(rec_ask)
    if tick <= 0:
        return None
    return round((rec_ask - rec_bid) / tick)


def _spread_bp(spread_ticks, price):
    """인정 스프레드를 bp 로. 가격이 틱 격자에 있으므로 (틱수 × 호가단위) = 스프레드(원).
    lib/hoga.ts spreadBp 와 같은 산식. 틱수/체결가가 없으면 None."""
    if spread_ticks is None:
        return None
    p = _to_num(price)
    if p is None or p <= 0:
        return None
    return (spread_ticks * _tick_size(p)) / p * 10_000


def _band_of(bp):
    """bp → 심각도 구간 키. lib/hoga.ts spreadSeverity 와 경계가 같아야 한다."""
    if bp is None:
        return None
    if bp >= SPREAD_CRIT_BP:
        return "crit"
    if bp >= SPREAD_WARN_BP:
        return "warn"
    return "calm"


def _bucket(spread_ticks, price=None) -> int:
    """틱 값을 히스토그램 버킷으로. 화면 요약과 같은 기준을 쓴다 (2026-07-30 통일).

    · _NONE_TICK('없음') = 인정호가 부재(None) 뿐이다 = 화면의 '물량X'. 구 기준의
      '20틱 초과'는 빠졌다 — 화면이 아무리 벌어져도 그 bp 를 그대로 보여주므로
      여기서도 숫자 버킷으로 남긴다(lib/hoga.ts lpQuoteMissing 주석 참고).
    · _OK_TICK('정상')   = 옅은 회색 밴드(<SPREAD_WARN_BP=20bp). 체결가가 있으면 bp 로
      비교하고, 없으면 구 틱 기준으로 폴백한다.
    """
    if spread_ticks is None:
        return _NONE_TICK
    p = _to_num(price)
    if p is not None and p > 0:
        bp = (spread_ticks * _tick_size(p)) / p * 10_000
        return _OK_TICK if bp < SPREAD_WARN_BP else int(spread_ticks)
    if spread_ticks < SPREAD_ALERT_MIN_TICKS:
        return _OK_TICK
    return int(spread_ticks)


def _connect():
    ensure_dirs()
    con = sqlite3.connect(DB_PATH, timeout=5.0)
    con.execute(
        "CREATE TABLE IF NOT EXISTS lp_spread_min ("
        " trade_date TEXT NOT NULL, code TEXT NOT NULL, basis TEXT NOT NULL,"
        " tick INTEGER NOT NULL, count INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (trade_date, code, basis, tick))"
    )
    # 시계열(분봉용) — 표본 시각(ts=HH:MM:SS KST)별 원본 인정 스프레드 틱을 그대로
    # 기록한다. 집계(lp_spread_min)와 달리 버킷을 씌우지 않아 1·2틱도 구분되고,
    # '없음'(인정호가 부재)은 NULL 로 둔다. 나중에 틱 변화 시계열 차트에 쓴다
    # (2026-07-28 사용자 요청). trade_date+ts 로 절대시각 복원.
    con.execute(
        "CREATE TABLE IF NOT EXISTS lp_spread_ts ("
        " trade_date TEXT NOT NULL, ts TEXT NOT NULL, code TEXT NOT NULL,"
        " basis TEXT NOT NULL, tick INTEGER, bp REAL, price REAL,"
        " PRIMARY KEY (trade_date, code, basis, ts))"
    )
    # bp/price 는 2026-07-30 추가(구간별 통계용) — 기존 DB 에는 열이 없으므로 보강한다.
    # 틱만으로는 bp 를 되살릴 수 없다(그 시각 체결가가 필요) → 그 전 표본은 구간 분류
    # 대상에서 빠지고, build_lp_eval 이 unbanded_min 으로 그 분수를 드러낸다.
    existing = {r[1] for r in con.execute("PRAGMA table_info(lp_spread_ts)")}
    for col, decl in (("bp", "REAL"), ("price", "REAL")):
        if col not in existing:
            con.execute(f"ALTER TABLE lp_spread_ts ADD COLUMN {col} {decl}")
    # 괴리율 시계열(종목별) — 실제괴리(actual_dev=자체 iNAV 기준 deviation_pct)와
    # 장중괴리(intraday_dev=거래소 공시 premiumIntra)를 표본 시각별로 기록한다.
    # basis(LP/총호가)와 무관하므로 종목당 1행 (2026-07-28 사용자 요청). 값 없으면 NULL.
    con.execute(
        "CREATE TABLE IF NOT EXISTS lp_dev_ts ("
        " trade_date TEXT NOT NULL, ts TEXT NOT NULL, code TEXT NOT NULL,"
        " actual_dev REAL, intraday_dev REAL,"
        " PRIMARY KEY (trade_date, code, ts))"
    )
    return con


def sample_once(hoga: dict | None, now: datetime | None = None,
                snapshot: dict | None = None) -> int:
    """현재 호가 스냅샷에서 ACE 9종의 인정 스프레드 틱을 basis 2종으로 표본해 1분
    (=1표본)씩 누적한다. snapshot(iNAV 스냅샷)이 주어지면 같은 ts 로 종목별 괴리율
    (실제/장중)도 함께 기록한다. 누적한 (code×basis) 행 수를 반환(0=구간밖/스킵)."""
    now = now or datetime.now(_KST)
    minute = now.hour * 60 + now.minute
    if not (SESSION_START_MIN <= minute < SESSION_END_MIN):
        return 0
    if not hoga:
        return 0
    age = hoga.get("hoga_last_received_age_s")
    if age is None or age > HOGA_FRESH_MAX_S:
        return 0  # CHECK 끊김/지연 — 표본하지 않음
    payload = hoga.get("payload") or {}
    etfs = payload.get("etfs") or []
    by_code = {str(e.get("code")): e for e in etfs}
    trade_date = now.strftime("%Y-%m-%d")
    ts = now.strftime("%H:%M:%S")
    rows = []       # 집계: (trade_date, code, basis, 버킷틱)
    # 시계열: (trade_date, ts, code, basis, 원본틱, bp, 체결가) — 없음=None→NULL.
    # bp 를 함께 남기는 이유: 틱만 있으면 그 시각 체결가를 몰라 나중에 bp 를 되살릴 수
    # 없다(구간별 통계가 bp 기준이라 필수). price 도 같이 남겨 경계값을 바꿔도 재계산
    # 가능하게 한다 (2026-07-30).
    ts_rows = []
    for code in ACE_TICKERS:
        e = by_code.get(code)
        if not e:
            continue
        # 'lp' 는 10단 사다리(2026-07-29 CHECK 확장)로 화면 알림과 동일 기준.
        # 'total' 은 askQtys(5단)를 그대로 쓴다 — askQtys10 이 전 종목 0 으로 오기
        # 때문(CHECK 미채움). 사다리가 10단이어도 잔량이 5개면 뒤는 자동으로 건너뛴다.
        ask_ladder = _ladder_prices(e.get("askPrices10"), e.get("askPrices"), "ask")
        bid_ladder = _ladder_prices(e.get("bidPrices10"), e.get("bidPrices"), "bid")
        price = _to_num(e.get("price"))
        for basis, aq, bq in (
            ("lp", e.get("lpAskQtys"), e.get("lpBidQtys")),
            ("total", e.get("askQtys"), e.get("bidQtys")),
        ):
            st = _recognized_spread_ticks(ask_ladder, aq, bid_ladder, bq)
            rows.append((trade_date, code, basis, _bucket(st, price)))
            ts_rows.append(
                (trade_date, ts, code, basis, st, _spread_bp(st, price), price)
            )
    if not rows:
        return 0
    # 괴리율 시계열(종목별, basis 무관) — iNAV 스냅샷에서 실제괴리(deviation_pct)와
    # 장중괴리(intraday_dev_pct=거래소 공시)를 같은 ts 로 기록. 값 없으면 NULL.
    dev_rows = []
    snap_by_code = {
        str(se.get("ticker")): se for se in ((snapshot or {}).get("etfs") or [])
    }
    for code in ACE_TICKERS:
        se = snap_by_code.get(code)
        if se is None:
            continue
        dev_rows.append((
            trade_date, ts, code,
            _to_num(se.get("deviation_pct")),
            _to_num(se.get("intraday_dev_pct")),
        ))
    con = _connect()
    try:
        con.executemany(
            "INSERT INTO lp_spread_min (trade_date, code, basis, tick, count) "
            "VALUES (?,?,?,?,1) "
            "ON CONFLICT(trade_date, code, basis, tick) DO UPDATE SET count=count+1",
            rows,
        )
        con.executemany(
            "INSERT INTO lp_spread_ts (trade_date, ts, code, basis, tick, bp, price) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(trade_date, code, basis, ts) DO UPDATE SET "
            "tick=excluded.tick, bp=excluded.bp, price=excluded.price",
            ts_rows,
        )
        if dev_rows:
            con.executemany(
                "INSERT INTO lp_dev_ts (trade_date, ts, code, actual_dev, intraday_dev) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(trade_date, code, ts) DO UPDATE SET "
                "actual_dev=excluded.actual_dev, intraday_dev=excluded.intraday_dev",
                dev_rows,
            )
        con.commit()
    finally:
        con.close()
    return len(rows)


def _stats(bucket_counts: dict) -> dict:
    """알림 버킷에 대한 평균·최빈·중앙값(분 가중). '없음'/'정상'은 제외 — 숫자 틱이
    아니므로 분포 통계 밖에서 별도 카운트로 본다. _bucket 이 하한(15bp) 미만을 이미
    _OK_TICK 으로 접었으므로 여기서는 양수 틱만 걸러면 된다 (2026-07-30)."""
    alert = {t: c for t, c in bucket_counts.items() if t > _OK_TICK and c > 0}
    total = sum(alert.values())
    if total == 0:
        return {"mean": None, "mode": None, "median": None, "alert_min": 0}
    mean = sum(t * c for t, c in alert.items()) / total
    mode = max(alert.items(), key=lambda kv: (kv[1], -kv[0]))[0]  # 최빈, 동률=작은 틱
    half = total / 2
    cum = 0
    median = None
    for t, c in sorted(alert.items()):
        cum += c
        if cum >= half:
            median = t
            break
    return {"mean": round(mean, 2), "mode": mode, "median": median, "alert_min": total}


def _band_row(key: str, label: str, values: list) -> dict:
    """한 구간의 유지 분수 + bp 통계. 표본 1건 = 1분이므로 개수가 곧 유지 분수다.
    최빈은 bp 가 연속값이라 그대로는 의미가 없어 **1bp 단위로 반올림**해 최다 값을
    고른다(동률이면 작은 쪽). (2026-07-30 사용자 요청: 구간별 유지분수·평균·최빈)"""
    n = len(values)
    if n == 0:
        return {"key": key, "label": label, "minutes": 0,
                "mean": None, "mode": None, "median": None}
    vals = sorted(values)
    counter: dict[int, int] = {}
    for v in vals:
        k = int(round(v))
        counter[k] = counter.get(k, 0) + 1
    mode = max(counter.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    median = (vals[n // 2] if n % 2
              else (vals[n // 2 - 1] + vals[n // 2]) / 2)
    return {
        "key": key, "label": label, "minutes": n,
        "mean": round(sum(vals) / n, 1),
        "mode": mode,
        "median": round(median, 1),
    }


def _bands(acc: dict) -> list:
    """구간 4종을 화면 순서(좁은 → 넓은 → 없음)로. 경계는 lib/hoga.ts 와 동일."""
    return [
        _band_row("calm", f"0~{SPREAD_WARN_BP}bp", acc["calm"]),
        _band_row("warn", f"{SPREAD_WARN_BP}~{SPREAD_CRIT_BP}bp", acc["warn"]),
        _band_row("crit", f"{SPREAD_CRIT_BP}bp↑", acc["crit"]),
        # '없음' = 인정호가 부재(물량X). bp 가 없으므로 유지 분수만.
        {"key": "none", "label": "없음", "minutes": acc["none"],
         "mean": None, "mode": None, "median": None},
    ]


def _hist(bucket_counts: dict) -> dict:
    out = {}
    for tick, c in sorted(bucket_counts.items()):
        key = "none" if tick == _NONE_TICK else "ok" if tick == _OK_TICK else str(tick)
        out[key] = c
    return out


def build_lp_eval(trade_date: str | None = None, names: dict | None = None,
                  basis: str | None = None) -> dict:
    """일별 LP 평가 — ACE 9종 × basis(lp/total) 히스토그램 + 통계.

    basis 인자가 'lp'/'total' 이면 그 기준만, 아니면 둘 다 반환.
    """
    names = names or {}
    now = datetime.now(_KST)
    today = now.strftime("%Y-%m-%d")
    out = {
        "trade_date": trade_date or today,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "session": {"start": _hhmm(SESSION_START_MIN), "end": _hhmm(SESSION_END_MIN)},
        "recognized_qty_min": RECOGNIZED_QTY_MIN,
        "warn_bp": SPREAD_WARN_BP,
        "crit_bp": SPREAD_CRIT_BP,
        # 표본 구간 전체 분수 — 구간별 유지 분수 합이 이 값에 얼마나 닿는지로 수신
        # 정상 여부를 읽을 수 있다 (끊김/지연 분은 표본하지 않으므로 모자란다).
        "session_minutes": SESSION_END_MIN - SESSION_START_MIN,
        "available_dates": [],
        "etfs": [],
    }
    if not DB_PATH.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        _log(f"open failed: {exc!r}")
        return out
    try:
        cur = con.cursor()
        out["available_dates"] = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT trade_date FROM lp_spread_min ORDER BY trade_date DESC"
            )
        ]
        # 날짜 미지정이면 가장 최근 누적일로 조회한다 — 오늘(장전/휴장)이 아직 비어
        # 있어 빈 화면이 뜨는 대신 마지막으로 쌓인 날을 보여준다. 오늘 데이터가 있으면
        # 그 날이 available_dates[0] 이라 그대로 오늘 (2026-07-28 사용자 요청).
        query_date = trade_date or (
            out["available_dates"][0] if out["available_dates"] else today
        )
        out["trade_date"] = query_date
        data: dict = {}
        for code, b, tick, count in cur.execute(
            "SELECT code, basis, tick, count FROM lp_spread_min WHERE trade_date=?",
            (query_date,),
        ):
            data.setdefault((code, b), {})[tick] = count
        # 구간별 통계는 시계열(표본 1건=1분)에서 직접 낸다 — 집계 테이블은 틱 버킷이라
        # 20~40 / 40↑ 를 가를 수 없다. bp 기록 전(2026-07-30 이전) 표본은 tick 은 있는데
        # bp 가 NULL 이므로 unbanded 로 따로 세어 화면이 그 사실을 드러내게 한다.
        bands: dict = {}
        for code, b, tick, bp_val in cur.execute(
            "SELECT code, basis, tick, bp FROM lp_spread_ts WHERE trade_date=?",
            (query_date,),
        ):
            acc = bands.setdefault(
                (code, b),
                {"calm": [], "warn": [], "crit": [], "none": 0, "unbanded": 0},
            )
            if tick is None:
                acc["none"] += 1
            elif bp_val is None:
                acc["unbanded"] += 1
            else:
                acc[_band_of(bp_val)].append(bp_val)
    except sqlite3.Error as exc:
        _log(f"query failed: {exc!r}")
        con.close()
        return out
    con.close()

    bases = (basis,) if basis in ("lp", "total") else ("lp", "total")
    for code in ACE_TICKERS:
        entry = {"code": code, "name": names.get(code, "") or names.get(code.upper(), ""),
                 "basis": {}}
        for b in bases:
            bc = data.get((code, b), {})
            st = _stats(bc)
            acc = bands.get(
                (code, b),
                {"calm": [], "warn": [], "crit": [], "none": 0, "unbanded": 0},
            )
            entry["basis"][b] = {
                "hist": _hist(bc),
                "none_min": bc.get(_NONE_TICK, 0),
                "ok_min": bc.get(_OK_TICK, 0),
                "alert_min": st["alert_min"],
                "total_min": sum(bc.values()),
                "mean_tick": st["mean"],
                "mode_tick": st["mode"],
                "median_tick": st["median"],
                # 2026-07-30 신설 — 화면 통계표의 정본. bands 의 minutes 합 + unbanded_min
                # = 그 날 표본 분수(=장중 수신이 정상이었던 분수).
                "bands": _bands(acc),
                "unbanded_min": acc["unbanded"],
            }
        out["etfs"].append(entry)
    return out


def build_lp_eval_ts(trade_date: str | None = None, names: dict | None = None,
                     basis: str | None = None) -> dict:
    """인정 스프레드 틱 시계열(분봉) — ACE 종목별 (ts, tick) 포인트 배열. 차트용.
    basis 'lp'/'total'(기본 lp). tick=None 은 '없음'(인정호가 부재)=선 끊김.
    available_dates 는 시계열이 기록된 날(lp_spread_ts)만 — 시간 미기록 과거일 제외
    (2026-07-28 사용자 요청: 28일자부터 x=시간·y=틱 추이 차트)."""
    names = names or {}
    now = datetime.now(_KST)
    today = now.strftime("%Y-%m-%d")
    basis = basis if basis in ("lp", "total") else "lp"
    out = {
        "trade_date": trade_date or today,
        "basis": basis,
        "session": {"start": _hhmm(SESSION_START_MIN), "end": _hhmm(SESSION_END_MIN)},
        "available_dates": [],
        "series": [],
    }
    if not DB_PATH.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        _log(f"ts open failed: {exc!r}")
        return out
    by_code: dict = {}
    try:
        cur = con.cursor()
        out["available_dates"] = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT trade_date FROM lp_spread_ts ORDER BY trade_date DESC"
            )
        ]
        query_date = trade_date or (
            out["available_dates"][0] if out["available_dates"] else today
        )
        out["trade_date"] = query_date
        for code, ts, tick in cur.execute(
            "SELECT code, ts, tick FROM lp_spread_ts "
            "WHERE trade_date=? AND basis=? ORDER BY code, ts",
            (query_date, basis),
        ):
            by_code.setdefault(code, []).append([ts, tick])
    except sqlite3.Error as exc:
        # 테이블 미생성(첫 표본 전) 등 — 빈 시계열로.
        _log(f"ts query skipped: {exc!r}")
        con.close()
        return out
    con.close()
    for code in ACE_TICKERS:
        out["series"].append({
            "code": code,
            "name": names.get(code, "") or names.get(code.upper(), ""),
            "points": by_code.get(code, []),
        })
    return out


# ── 일별 산출물 저장 (S: 아카이브) ─────────────────────────────────────────
# DB 는 재빌드에 살아남는 named 볼륨이지만 컨테이너 안이다. 사용자 요청으로 하루치
# 통계를 S: 폴더에 별도 보관한다 (2026-07-27):
#   · lp_eval_{date}.json   — 그날 완전본(build_lp_eval, 히스토그램·통계, 두 basis)
#   · lp_eval_history.csv    — 전 거래일 요약 마스터(일자×ETF×basis 한 행, 추세분석용)
# 매 표본(60초)마다 덮어쓴다 → 15:20(의무 종료)에 자연히 그날 최종본이 된다.

# 마스터 CSV 컬럼 — 일자 추세용 요약(틱별 히스토그램 전체는 일별 JSON 에 있다).
_CSV_HEADER = [
    "trade_date", "code", "name", "basis",
    "total_min", "none_min", "ok_min", "alert_min",
    "mean_tick", "mode_tick", "median_tick",
]


def _all_buckets_by_key() -> dict:
    """DB 전체를 (trade_date, code, basis) -> {tick: count} 로 모은다(read-only)."""
    data: dict = {}
    if not DB_PATH.exists():
        return data
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        _log(f"master open failed: {exc!r}")
        return data
    try:
        for td, code, b, tick, count in con.execute(
            "SELECT trade_date, code, basis, tick, count FROM lp_spread_min"
        ):
            data.setdefault((td, code, b), {})[tick] = count
    except sqlite3.Error as exc:
        _log(f"master query failed: {exc!r}")
    finally:
        con.close()
    return data


def _write_master_csv(out_dir: Path, names: dict) -> None:
    """전 거래일 요약을 마스터 CSV 로 원자적 교체 저장. 정렬=일자↑·ACE순·lp먼저.
    Excel 한글 대응 UTF-8 BOM. 부분쓰기 노출 방지로 .tmp → replace."""
    data = _all_buckets_by_key()
    ace_rank = {c: i for i, c in enumerate(ACE_TICKERS)}
    basis_rank = {"lp": 0, "total": 1}
    keys = sorted(
        data.keys(),
        key=lambda k: (k[0], ace_rank.get(k[1], 99), basis_rank.get(k[2], 9)),
    )
    tmp = out_dir / "lp_eval_history.csv.tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(_CSV_HEADER)
        for (td, code, b) in keys:
            bc = data[(td, code, b)]
            st = _stats(bc)
            w.writerow([
                td, code,
                names.get(code, "") or names.get(code.upper(), ""), b,
                sum(bc.values()), bc.get(_NONE_TICK, 0), bc.get(_OK_TICK, 0),
                st["alert_min"],
                "" if st["mean"] is None else st["mean"],
                "" if st["mode"] is None else st["mode"],
                "" if st["median"] is None else st["median"],
            ])
    tmp.replace(out_dir / "lp_eval_history.csv")


def write_daily_snapshot(names: dict | None = None) -> bool:
    """오늘치 JSON + 전기간 마스터 CSV 를 S: 출력폴더에 덮어쓴다. 폴더가 없으면
    조용히 skip(로컬·마운트 부재). 파일별로 예외를 삼켜 한쪽이 잠겨도(예: Excel
    로 CSV 오픈 중) 다른 쪽 저장은 진행한다."""
    out_dir = LP_EVAL_OUT_DIR
    if not out_dir.is_dir():
        return False
    names = names or {}
    today = datetime.now(_KST).strftime("%Y-%m-%d")
    ok = True
    try:
        snap = build_lp_eval(today, names)
        tmp = out_dir / f"lp_eval_{today}.json.tmp"
        tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(out_dir / f"lp_eval_{today}.json")
    except OSError as exc:
        _log(f"daily json write failed: {exc!r}")
        ok = False
    try:
        _write_master_csv(out_dir, names)
    except OSError as exc:
        _log(f"master csv write failed: {exc!r}")
        ok = False
    return ok
