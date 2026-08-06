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

같은 표본 시각에 종목별 괴리율(실제괴리 = 자체 iNAV 기준 / 장중괴리 = 거래소 공시)도
lp_dev_ts 에 함께 기록한다 — 스프레드가 벌어진 순간의 괴리를 나중에 붙여볼 수 있게
(2026-07-28). S: 아카이브의 lp_eval_ts_{date}.csv 가 둘을 한 행으로 합쳐 내보낸다.

프론트 lib/hoga.ts 의 recognizedSpread/recognizedQuotePrice/spreadBp/tickSize 를 그대로
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
# (09:00~09:05)과 종가 단일가 구간(15:20~15:30)은 LP 의무가 면제·종료되므로 평가에
# 넣지 않는다 (2026-07-27 사용자 확정). 단 09:00~09:05 는 2026-08-04 부터 별도
# 테이블(lp_pre_ts)에 보관만 한다 — 아래 PRE_START_MIN 주석 참고.
# CHECK 수신 지연이 크면(끊김) 그 분은 제외.
SESSION_START_MIN = 9 * 60 + 5      # 09:05
SESSION_END_MIN = 15 * 60 + 20      # 15:20

# 개장 직후 5분(09:00~09:05) — LP 호가 의무가 아직 없는 구간이라 평가에서는 계속
# 뺀다. 다만 "의무가 없을 때 LP 가 어떻게 까는가"는 그 자체로 볼 값어치가 있어서
# 표본만 따로 쌓아둔다 (2026-08-04 사용자 요청: 화면 표시 목적 아님, 저장만).
# 격리 방식 = 전용 테이블 lp_pre_ts + 전용 CSV. 집계 쿼리들이 보는 lp_spread_min /
# lp_spread_ts / lp_dev_ts 에는 한 줄도 안 들어가므로 대시보드 숫자는 그대로다.
PRE_START_MIN = 9 * 60              # 09:00 개장
SESSION_MINUTES = SESSION_END_MIN - SESSION_START_MIN   # 375 = '총 장 기간'(표본 만수)
HOGA_FRESH_MAX_S = 15.0

# 시간대별 평균 — 전 종목에 낸다 (2026-08-04). 처음엔 중국 편입 3종만 봤는데(중국 장
# 개시 전후로 LP 태도가 갈린다), 원자산 개장·환율·점심 등으로 시간대가 갈리는 건
# 어느 ETF나 마찬가지라 전 종목으로 넓혔다. 화면은 Topbar '구간분석' 토글로 켠다.

# 실제괴리 표시용 임시 미러 — 웹 inav/page.tsx 의 DEV_MIRROR_TICKERS 와 같은 집합을
# 유지해야 두 화면이 같은 '실제괴리'를 말한다. 0199C0 은 구성종목이 전부 국내라
# 실제괴리와 장중괴리가 원리상 같아야 하는데 자체 iNAV 가 어긋나 있어(8/4 실측
# 0.542% vs 0.163%) 거래소 공시값으로 덮어 쓴다. DB 원본(lp_dev_ts)과 CSV 는 손대지
# 않고 집계 단계에서만 바꾼다. ※ 원인 규명 후 웹 쪽 블록과 함께 통째로 제거할 것.
DEV_MIRROR_TICKERS = frozenset({"0199C0"})

# (키, 라벨, 짧은라벨, 시작분, 종료분) — 종료는 배타(start <= m < end), 세션 판정과
# 같은 규칙. w1~w4 는 빈틈없이 이어져 있어 짧은라벨(시작시각)만으로 구간이 특정된다
# — 카드에 5칸을 나란히 놓으면 '09:05~10:30' 전체를 적을 폭이 안 나온다.
# w5 는 장 전체라 mean_bp(대표값)와 같은 값이 나온다 — 비교 기준선으로 같이 세운다.
# ⚠️ w4 의 종료 15:30 은 사용자 지정 라벨이고, 실제 표본은 LP 의무가 끝나는 15:20
#    까지만 있다(SESSION_END_MIN). 즉 w4 는 90분이 아니라 최대 80분이 분모다.
SPREAD_WINDOWS = (
    ("w1", "09:05~10:30", "09:05", 9 * 60 + 5, 10 * 60 + 30),
    ("w2", "10:30~13:00", "10:30", 10 * 60 + 30, 13 * 60),
    ("w3", "13:00~14:00", "13:00", 13 * 60, 14 * 60),
    ("w4", "14:00~15:30", "14:00", 14 * 60, 15 * 60 + 30),
    ("w5", "09:05~15:20", "전체", SESSION_START_MIN, SESSION_END_MIN),
)

_NONE_TICK = -1  # '없음' 센티넬
_OK_TICK = 0     # '정상'(<3틱) 센티넬

# 히스토그램 첫 막대 — 0~2틱(음수=교차호가 포함)을 한 칸으로 묶는다. 1틱과 2틱을
# 갈라 봐야 LP 평가에 쓸 게 없고, 셋을 합쳐야 '얼마나 촘촘했나'가 한눈에 들어온다.
_LOW_TICK_KEY = "0-2"
_LOW_TICK_MAX = 2


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


def _recognized_spread(ask_prices, ask_qtys, bid_prices, bid_qtys):
    """인정 스프레드 — (원, 틱수, MID). 한쪽이라도 인정호가가 없으면 None (= '없음').
    MID = (인정매도호가 + 인정매수호가) / 2. lib/hoga.ts recognizedSpread 이식."""
    rec_ask = _recognized_quote_price(ask_prices, ask_qtys)
    rec_bid = _recognized_quote_price(bid_prices, bid_qtys)
    if rec_ask is None or rec_bid is None:
        return None
    tick = _tick_size(rec_ask)
    if tick <= 0:
        return None
    won = rec_ask - rec_bid
    return won, round(won / tick), (rec_ask + rec_bid) / 2


def _spread_bp(won, mid):
    """인정 스프레드를 bp 로 — 분모는 **인정호가 MID**다 (2026-08-05 사용자 지정).

    전에는 체결가로 나눴다. 값 차이는 거의 없지만(같은 날 라이브 9종 실측: 평균
    0.005bp·최대 0.013bp) 분모의 성격이 다르다 — 체결가는 마지막 '체결'이라 거래가
    뜸하면 낡은 값이 남고, 스프레드가 벌어질수록 체결가가 매수·매도 중 어느 쪽에
    붙었느냐로 bp 가 흔들린다. MID 는 그 순간 호가에서 바로 나오므로 스프레드를
    재는 분모로 일관된다. lib/hoga.ts spreadBp 와 같은 산식(값 일치 보장)."""
    if won is None or mid is None or mid <= 0:
        return None
    return won / mid * 10_000


def _band_of(bp):
    """bp → 심각도 구간 키. lib/hoga.ts spreadSeverity 와 경계가 같아야 한다."""
    if bp is None:
        return None
    if bp >= SPREAD_CRIT_BP:
        return "crit"
    if bp >= SPREAD_WARN_BP:
        return "warn"
    return "calm"


def _bucket(spread_ticks, bp=None) -> int:
    """틱 값을 히스토그램 버킷으로. 화면 요약과 같은 기준을 쓴다 (2026-07-30 통일).

    · _NONE_TICK('없음') = 인정호가 부재(None) 뿐이다 = 화면의 '물량X'. 구 기준의
      '20틱 초과'는 빠졌다 — 화면이 아무리 벌어져도 그 bp 를 그대로 보여주므로
      여기서도 숫자 버킷으로 남긴다(lib/hoga.ts lpQuoteMissing 주석 참고).
    · _OK_TICK('정상')   = 옅은 회색 밴드(<SPREAD_WARN_BP=20bp). bp 가 오면 그걸로
      비교하고, 없으면 구 틱 기준으로 폴백한다.

    bp 를 인자로 받는다 — 여기서 다시 계산하면 분모(2026-08-05 부터 인정호가 MID)를
    두 곳에서 관리하게 되고, 한쪽만 고치면 버킷과 밴드가 조용히 어긋난다.
    """
    if spread_ticks is None:
        return _NONE_TICK
    if bp is not None:
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
    # 개장 직후(09:00~09:05) 전용 — LP 의무 면제 구간이라 위 3개 테이블과 완전히
    # 분리한다. 집계 쿼리가 이 테이블을 절대 읽지 않는 게 격리의 전부다.
    # 괴리는 basis 무관이지만 행이 하루 90개뿐(9종×2기준×5분)이라 열로 붙여 둔다.
    con.execute(
        "CREATE TABLE IF NOT EXISTS lp_pre_ts ("
        " trade_date TEXT NOT NULL, ts TEXT NOT NULL, code TEXT NOT NULL,"
        " basis TEXT NOT NULL, tick INTEGER, bp REAL, price REAL,"
        " actual_dev REAL, intraday_dev REAL,"
        " PRIMARY KEY (trade_date, code, basis, ts))"
    )
    return con


def sample_once(hoga: dict | None, now: datetime | None = None,
                snapshot: dict | None = None) -> int:
    """현재 호가 스냅샷에서 ACE 9종의 인정 스프레드 틱을 basis 2종으로 표본해 1분
    (=1표본)씩 누적한다. snapshot(iNAV 스냅샷)이 주어지면 같은 ts 로 종목별 괴리율
    (실제/장중)도 함께 기록한다. 누적한 (code×basis) 행 수를 반환(0=구간밖/스킵)."""
    now = now or datetime.now(_KST)
    minute = now.hour * 60 + now.minute
    # 판정·계산은 두 구간이 완전히 같고, 다른 건 '어느 테이블에 넣느냐' 뿐이다.
    in_main = SESSION_START_MIN <= minute < SESSION_END_MIN
    in_pre = PRE_START_MIN <= minute < SESSION_START_MIN
    if not (in_main or in_pre):
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
            spread = _recognized_spread(ask_ladder, aq, bid_ladder, bq)
            st = None if spread is None else spread[1]
            bp = None if spread is None else _spread_bp(spread[0], spread[2])
            rows.append((trade_date, code, basis, _bucket(st, bp)))
            ts_rows.append((trade_date, ts, code, basis, st, bp, price))
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
        if in_pre:
            # 의무 면제 구간 — 평가 테이블 3종에는 한 줄도 안 넣는다. 괴리를 basis
            # 행마다 복제해 붙여 한 테이블로 자립시킨다(조인 없이 CSV 로 바로 나감).
            dev_by_code = {r[2]: (r[3], r[4]) for r in dev_rows}
            pre_rows = [
                row + dev_by_code.get(row[2], (None, None)) for row in ts_rows
            ]
            con.executemany(
                "INSERT INTO lp_pre_ts (trade_date, ts, code, basis, tick, bp, price,"
                " actual_dev, intraday_dev) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(trade_date, code, basis, ts) DO UPDATE SET "
                "tick=excluded.tick, bp=excluded.bp, price=excluded.price, "
                "actual_dev=excluded.actual_dev, intraday_dev=excluded.intraday_dev",
                pre_rows,
            )
            con.commit()
            return len(pre_rows)
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


def _share(minutes: int) -> float:
    """유지 분수 → 총 장 기간(09:05~15:20 = SESSION_MINUTES) 대비 비율(%).
    분모를 '실제 표본 분수'가 아니라 장 전체로 잡는 이유: CHECK 수신이 끊긴 분까지
    포함해야 '하루 중 몇 %를 그 상태로 보냈나'가 부풀지 않는다. 그래서 구간 비율의
    합은 수신이 정상이었던 만큼만 100% 에 닿는다 (2026-08-04 사용자 요청)."""
    return round(minutes / SESSION_MINUTES * 100, 1)


def _band_row(key: str, label: str, values: list) -> dict:
    """한 구간의 유지 분수 + 비율 + bp 통계. 표본 1건 = 1분이므로 개수가 곧 유지 분수다.
    최빈은 bp 가 연속값이라 그대로는 의미가 없어 **1bp 단위로 반올림**해 최다 값을
    고른다(동률이면 작은 쪽). (2026-07-30 사용자 요청: 구간별 유지분수·평균·최빈
    / 2026-08-04 화면은 최빈 대신 share 를 쓴다 — mode 는 계약 유지용으로 남긴다.)"""
    n = len(values)
    if n == 0:
        return {"key": key, "label": label, "minutes": 0, "share": 0.0,
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
        "key": key, "label": label, "minutes": n, "share": _share(n),
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
        # '없음' = 인정호가 부재(물량X). bp 가 없으므로 유지 분수·비율만.
        # 라벨에 '(미제출)'을 붙인다 — 값이 안 잡힌 게 아니라 LP 가 1,000주 이상
        # 호가를 안 냈다는 뜻이라, '없음'만으로는 수집 실패로 읽힌다 (2026-08-05).
        {"key": "none", "label": "없음(미제출)", "minutes": acc["none"],
         "share": _share(acc["none"]), "mean": None, "mode": None, "median": None},
    ]


def _ts_minute(ts: str) -> int | None:
    """'HH:MM:SS' → 분 단위 시각. 형식이 깨진 표본은 None(구간 집계에서 제외)."""
    try:
        h, m, _ = ts.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _windows(acc: dict | None, digits: int = 1) -> list:
    """시간대별 평균 — SPREAD_WINDOWS 순서대로 [{key,label,mean,minutes}].
    분모는 그 구간의 유효 표본 수다(스프레드는 '없음'이 bp 가 없어 빠진다).
    표본이 하나도 없으면 mean=None → 화면은 '−'.

    digits: 스프레드(bp)는 1자리면 충분하지만 괴리(%)는 2자리를 써야 한다 — 1자리로
    끊으면 −0.26% 가 −0.3% 로, 0.04% 가 0.0% 로 뭉개져 구간 비교가 안 된다."""
    acc = acc or {}
    out = []
    for key, label, short, _s, _e in SPREAD_WINDOWS:
        vals = acc.get(key) or []
        out.append({
            "key": key, "label": label, "short": short,
            "mean": round(sum(vals) / len(vals), digits) if vals else None,
            "minutes": len(vals),
        })
    return out


def _dev_stats(vals: list, wacc: dict | None) -> dict:
    """실제괴리(%) 평균 — 카드 '평균 실제괴리' 박스용. basis(LP/총호가)와 무관해서
    ETF 단위로 낸다.

    mean 은 부호를 살린 평균이라 하루 내내 프리미엄/디스카운트로 치우쳤는지를 말하고,
    abs_mean 은 부호가 상쇄돼 mean 이 0 에 가까워지는 경우를 드러낸다(실측 414270:
    mean −0.216% vs abs 0.301%). 화면은 mean 을 크게, abs_mean 을 밑줄에 쓴다.
    wacc 가 오면 시간대별 평균도 같이 낸다(전 종목 — 화면 '구간분석' 토글이 고른다)."""
    out = {
        "mean": round(sum(vals) / len(vals), 3) if vals else None,
        "abs_mean": round(sum(abs(v) for v in vals) / len(vals), 3) if vals else None,
        "minutes": len(vals),
    }
    if wacc is not None:
        out["windows"] = _windows(wacc, digits=2)
    return out


def _day_mean_bp(acc: dict) -> tuple:
    """그 날 ETF 하나의 대표값 — 구간 구분 없이 bp 표본 전체의 시간가중 평균과 그
    표본 분수. 표본 1건 = 1분이라 단순 산술평균이 곧 시간가중 평균이다. '없음'(인정
    호가 부재)은 bp 자체가 없어 분모에서 빠지므로 화면이 '없음' 분수를 같이 보여
    줘야 오독이 없다 (2026-08-04 사용자 요청: 카드마다 평균 bp 대표값)."""
    vals = acc["calm"] + acc["warn"] + acc["crit"]
    if not vals:
        return None, 0
    return round(sum(vals) / len(vals), 1), len(vals)


def _hist(bucket_counts: dict) -> dict:
    out = {}
    for tick, c in sorted(bucket_counts.items()):
        key = "none" if tick == _NONE_TICK else "ok" if tick == _OK_TICK else str(tick)
        out[key] = c
    return out


def _tick_hist(tick_counts: dict | None, fallback: dict) -> dict:
    """히스토그램 — **원시 틱 분포**(lp_spread_ts)로 만든다. 0~2틱은 한 막대로 묶고
    3틱부터는 틱별로 센다 (2026-08-04 사용자 요청).

    구 히스토그램은 집계 테이블(lp_spread_min)에서 왔는데, 그건 20bp 미만을 전부
    'ok' 한 칸으로 접어버려서 촘촘한 구간이 통째로 안 보였다 — 비싼 ETF(예: 483320,
    23,270원)는 7틱까지도 20bp 미만이라 막대가 아예 안 떴다. 원시 틱은 가격과 무관한
    LP 호가 태도라 그대로 세는 게 맞다(가격 보정된 시각은 아래 bands 가 준다).

    0~2 버킷은 표본이 0 이어도 항상 내보낸다 — 카드끼리 첫 막대 위치를 맞추고
    '한 번도 2틱 이하로 좁힌 적 없음'을 0 으로 드러내기 위해서다.
    시계열이 없는 과거일(2026-07-28 이전)은 구 집계 버킷으로 폴백한다."""
    if not tick_counts:
        return _hist(fallback)
    out = {_LOW_TICK_KEY: tick_counts.get(_LOW_TICK_KEY, 0)}
    for key in sorted((k for k in tick_counts if k != _LOW_TICK_KEY), key=int):
        out[key] = tick_counts[key]
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
        # 시간대별 평균(전 종목) — 같은 스캔에서 ts 를 구간으로 접는다.
        wins: dict = {}
        # 히스토그램용 원시 틱 분포 — 0~2 는 한 칸, 3틱부터 틱별. bp 폴딩 안 함.
        ticks: dict = {}
        for code, b, ts, tick, bp_val in cur.execute(
            "SELECT code, basis, ts, tick, bp FROM lp_spread_ts WHERE trade_date=?",
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
            if tick is not None:
                tacc = ticks.setdefault((code, b), {})
                tkey = _LOW_TICK_KEY if tick <= _LOW_TICK_MAX else str(tick)
                tacc[tkey] = tacc.get(tkey, 0) + 1
            if bp_val is None:
                continue
            minute = _ts_minute(ts)
            if minute is None:
                continue
            wacc = wins.setdefault((code, b), {})
            for key, _label, _short, start, end in SPREAD_WINDOWS:
                if start <= minute < end:
                    wacc.setdefault(key, []).append(bp_val)
    except sqlite3.Error as exc:
        _log(f"query failed: {exc!r}")
        con.close()
        return out

    # 실제괴리 시계열 — basis 무관이라 종목당 한 벌. 테이블이 없는 구 DB 에서도
    # 페이지 전체가 죽지 않도록 여기만 따로 감싼다(괴리 박스만 '−' 로 비는 게 낫다).
    devs: dict = {}
    dev_wins: dict = {}
    try:
        for code, ts, actual, intraday in cur.execute(
            "SELECT code, ts, actual_dev, intraday_dev FROM lp_dev_ts WHERE trade_date=?",
            (query_date,),
        ):
            val = intraday if code in DEV_MIRROR_TICKERS else actual
            if val is None:
                continue
            devs.setdefault(code, []).append(val)
            minute = _ts_minute(ts)
            if minute is None:
                continue
            wacc = dev_wins.setdefault(code, {})
            for key, _label, _short, start, end in SPREAD_WINDOWS:
                if start <= minute < end:
                    wacc.setdefault(key, []).append(val)
    except sqlite3.Error as exc:
        _log(f"dev query skipped: {exc!r}")
    con.close()

    bases = (basis,) if basis in ("lp", "total") else ("lp", "total")
    for code in ACE_TICKERS:
        entry = {"code": code, "name": names.get(code, "") or names.get(code.upper(), ""),
                 "basis": {},
                 # 실제괴리 평균 — basis 토글과 무관해서 ETF 단위로 붙인다.
                 "dev": _dev_stats(devs.get(code, []), dev_wins.get(code, {}))}
        for b in bases:
            bc = data.get((code, b), {})
            st = _stats(bc)
            acc = bands.get(
                (code, b),
                {"calm": [], "warn": [], "crit": [], "none": 0, "unbanded": 0},
            )
            mean_bp, banded_min = _day_mean_bp(acc)
            entry["basis"][b] = {
                "hist": _tick_hist(ticks.get((code, b)), bc),
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
                # 2026-08-04 신설 — 카드 대표값. mean_bp = 그 날 bp 표본 전체 평균,
                # banded_min = 그 평균의 분모(분).
                "mean_bp": mean_bp,
                "banded_min": banded_min,
            }
            # 시간대별 평균 — 전 종목에 항상 넣는다(2026-08-04). 화면이 Topbar
            # '구간분석' 토글로 단일 대표값과 5구간 중 무엇을 보여줄지 고른다.
            entry["basis"][b]["windows"] = _windows(wins.get((code, b)))
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
#   · lp_eval_{date}.json     — 그날 완전본(build_lp_eval, 히스토그램·통계, 두 basis)
#   · lp_eval_ts_{date}.csv   — 그날 분단위 원시 시계열(호가 bp + 실제/장중 괴리 동행)
#   · lp_eval_pre_{date}.csv  — 개장 직후 09:00~09:05(LP 의무 면제 구간) 같은 컬럼
#   · lp_eval_history.csv     — 전 거래일 요약 마스터(일자×ETF×basis 한 행, 추세분석용)
# 매 표본(60초)마다 덮어쓴다 → 15:20(의무 종료)에 자연히 그날 최종본이 된다.

# 마스터 CSV 컬럼 — 일자 추세용 요약(틱별 히스토그램 전체는 일별 JSON 에 있다).
# mean_bp = 그 날 대표값(화면 카드와 같은 값), banded_min = 그 평균의 분모(분).
_CSV_HEADER = [
    "trade_date", "code", "name", "basis",
    "total_min", "none_min", "ok_min", "alert_min",
    "mean_bp", "banded_min",
    "mean_tick", "mode_tick", "median_tick",
]

# 분단위 시계열 CSV 컬럼 — 한 행 = (표본시각 × ETF). basis 2종을 옆으로 펼쳐 한 행에
# 담고(세로로 쌓으면 괴리율이 basis 마다 중복된다) 같은 표본의 실제괴리·장중괴리를
# 붙인다 (2026-08-04 사용자 요청: 호가물량 bp 와 실제괴리를 같이 저장).
#   · lp_*    = LP 물량 기준 인정 스프레드(리테일 제외)
#   · total_* = 총호가 기준(리테일 포함, 화면 전광판과 동일)
#   · tick 빈칸 = '없음'(5단 안에 1,000주↑ 인정호가 부재) → bp 도 빈칸
#   · actual_dev   = 실제괴리(%) — 자체 iNAV 기준
#   · intraday_dev = 장중괴리(%) — 거래소 공시(premiumIntra)
_TS_CSV_HEADER = [
    "trade_date", "ts", "code", "name", "price",
    "lp_tick", "lp_bp", "total_tick", "total_bp",
    "actual_dev", "intraday_dev",
]


def _csv_append_state(path: Path, header: list) -> str | None:
    """이어쓰기 준비 — 반환값 = 이미 파일에 들어간 마지막 ts(없으면 None).

    시계열 CSV 는 한 번 쓰인 행이 절대 안 바뀌는 append-only 데이터라 매 표본마다
    하루치를 통째로 다시 쓸 이유가 없다(2026-08-05 실측 204KB·167ms). 이어쓰기
    지점은 **파일 자체**에서 읽는다 — 메모리에 들고 있으면 컨테이너가 재기동할 때
    잃어버리고, 파일을 기준으로 하면 쓰기가 한 번 실패해도(예: Excel 이 잠금) 다음
    표본에서 빠진 구간까지 알아서 따라잡는다.

    · 파일 없음/빈 파일        → 헤더만 쓰고 None
    · 헤더가 지금 스펙과 다름  → 컬럼이 바뀐 것이므로 헤더부터 새로 쓴다(자동 복구)
    · 마지막 줄이 개행으로 안 끝남 → 쓰다 만 줄이므로 잘라낸다
    · **마지막 ts 그룹은 통째로 되감는다** — 한 표본시각에 종목 수만큼(9행) 붙는데
      쓰다가 끊기면 그 그룹이 반만 남는다. 그 상태로 `ts > 마지막ts` 를 조회하면
      남은 반이 영영 빠지므로, 그룹 전체를 잘라내고 직전 ts 를 체크포인트로 준다.
    """
    head_line = ",".join(header)
    try:
        size = path.stat().st_size if path.exists() else 0
    except OSError:
        size = 0

    def _fresh() -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(header)

    if size == 0:
        _fresh()
        return None
    with open(path, "rb") as f:
        first = f.readline().decode("utf-8-sig", errors="replace").strip()
        if first != head_line:
            _log(f"{path.name}: 헤더가 바뀌어 전체 재작성")
            _fresh()
            return None
        start = max(0, size - 8192)
        f.seek(start)
        tail = f.read()
    # 쓰다 만 마지막 줄 정리
    if not tail.endswith(b"\n"):
        cut = tail.rfind(b"\n")
        if cut < 0:
            _fresh()
            return None
        size = start + cut + 1
        with open(path, "r+b") as f:
            f.truncate(size)
        tail = tail[: cut + 1]

    def _ts_of(raw_line: bytes) -> str | None:
        # ts 는 2번째 컬럼 'HH:MM:SS'. 헤더 줄('ts')은 콜론 수로 걸러진다.
        parts = raw_line.decode("utf-8", errors="replace").split(",")
        return parts[1] if len(parts) > 1 and parts[1].count(":") == 2 else None

    lines = tail[:-1].split(b"\n")
    if start > 0:
        lines = lines[1:]   # 창 경계에서 잘린 첫 줄은 신뢰할 수 없다
    last_ts = prev_ts = None
    drop = 0                # 잘라낼 바이트(마지막 ts 그룹)
    for raw_line in reversed(lines):
        ts = _ts_of(raw_line)
        if ts is None:
            break
        if last_ts is None:
            last_ts = ts
        if ts != last_ts:
            prev_ts = ts
            break
        drop += len(raw_line) + 1
    if last_ts is None:
        return None         # 헤더뿐 — 처음부터 채우면 된다
    if prev_ts is None:
        # 창 안이 전부 한 ts 그룹 = 그룹이 창 밖까지 이어질 수 있다(사실상 첫 표본
        # 직후에만 발생). 판단이 안 서면 안전하게 처음부터 다시 쓴다.
        _fresh()
        return None
    with open(path, "r+b") as f:
        f.truncate(size - drop)
    return prev_ts


def _csv_append(path: Path, rows: list) -> None:
    """행을 이어붙인다. utf-8-sig 로 열면 BOM 이 파일 중간에 박히므로 utf-8 로 연다
    (헤더를 쓸 때만 utf-8-sig 를 쓴다 — Excel 한글 대응은 그걸로 충분하다)."""
    if not rows:
        return
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)


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


# 마스터 CSV 용 평균 bp 캐시 — trade_date -> {(code, basis): (평균bp, 표본분수)}.
# 지난 거래일 값은 두 번 다시 안 변하는데 매 표본(60초)마다 lp_spread_ts 전체를
# GROUP BY 하고 있었다(2026-08-05 실측 5만행·130ms, 매일 3,300행씩 증가). 오늘치만
# 다시 세고 과거일은 프로세스 캐시에서 꺼낸다. 재기동하면 첫 1회만 전량 집계한다.
_BP_STATS_CACHE: dict = {}


def _all_bp_stats(today: str) -> dict:
    """(trade_date, code, basis) -> (평균bp, 표본분수) (read-only).
    bp 가 NULL 인 표본(2026-07-30 이전)은 SQL 집계에서 자동으로 빠진다."""
    if not DB_PATH.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        _log(f"bp stats open failed: {exc!r}")
        return {}
    try:
        dates = [r[0] for r in con.execute(
            "SELECT DISTINCT trade_date FROM lp_spread_ts"
        )]
        # 오늘은 계속 쌓이는 중이라 항상 다시 센다. 나머지는 캐시에 없을 때만.
        need = [d for d in dates if d == today or d not in _BP_STATS_CACHE]
        if need:
            marks = ",".join("?" * len(need))
            fresh: dict = {d: {} for d in need}
            for td, code, b, avg_bp, n in con.execute(
                "SELECT trade_date, code, basis, AVG(bp), COUNT(bp) FROM lp_spread_ts "
                f"WHERE bp IS NOT NULL AND trade_date IN ({marks}) "
                "GROUP BY trade_date, code, basis", need,
            ):
                fresh[td][(code, b)] = (round(avg_bp, 1), n)
            _BP_STATS_CACHE.update(fresh)
    except sqlite3.Error as exc:
        _log(f"bp stats query failed: {exc!r}")
        con.close()
        return {}
    finally:
        con.close()
    return {
        (d, code, b): v
        for d, m in _BP_STATS_CACHE.items()
        for (code, b), v in m.items()
    }


def _write_master_csv(out_dir: Path, names: dict) -> None:
    """전 거래일 요약을 마스터 CSV 로 원자적 교체 저장. 정렬=일자↑·ACE순·lp먼저.
    Excel 한글 대응 UTF-8 BOM. 부분쓰기 노출 방지로 .tmp → replace."""
    data = _all_buckets_by_key()
    bp_stats = _all_bp_stats(datetime.now(_KST).strftime("%Y-%m-%d"))
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
            mean_bp, banded_min = bp_stats.get((td, code, b), (None, 0))
            w.writerow([
                td, code,
                names.get(code, "") or names.get(code.upper(), ""), b,
                sum(bc.values()), bc.get(_NONE_TICK, 0), bc.get(_OK_TICK, 0),
                st["alert_min"],
                "" if mean_bp is None else mean_bp, banded_min,
                "" if st["mean"] is None else st["mean"],
                "" if st["mode"] is None else st["mode"],
                "" if st["median"] is None else st["median"],
            ])
    tmp.replace(out_dir / "lp_eval_history.csv")


def _rows_to_csv(rows: dict, names: dict, trade_date: str) -> list:
    """(ts, code) -> 필드 dict 를 _TS_CSV_HEADER 순서의 행 리스트로. 정렬 = ts↑·ACE순.
    본장·개장직후 CSV 가 같은 컬럼을 쓰므로 조판은 여기 한 곳에서만 한다."""
    ace_rank = {c: i for i, c in enumerate(ACE_TICKERS)}
    blank = lambda v: "" if v is None else v  # noqa: E731
    out = []
    for (ts, code) in sorted(rows, key=lambda k: (k[0], ace_rank.get(k[1], 99))):
        r = rows[(ts, code)]
        out.append([
            trade_date, ts, code,
            names.get(code, "") or names.get(code.upper(), ""),
            blank(r.get("price")),
            blank(r.get("lp_tick")), blank(r.get("lp_bp")),
            blank(r.get("total_tick")), blank(r.get("total_bp")),
            blank(r.get("actual_dev")), blank(r.get("intraday_dev")),
        ])
    return out


def _write_ts_csv(out_dir: Path, names: dict, trade_date: str) -> None:
    """그 날 분단위 원시 시계열을 CSV 에 **이어쓴다** — 호가 bp(basis 2종)와
    같은 표본시각의 실제/장중 괴리를 한 행에 담는다.

    구동은 lp_spread_ts(호가) 쪽이고 lp_dev_ts(괴리)는 (ts, code) 로 붙인다 —
    호가 표본이 없는 시각은 애초에 bp 도 없으므로 행이 생기지 않는다. 두 테이블은
    sample_once 한 번에 같은 ts 문자열로 함께 기록되므로 키가 어긋나지 않는다.

    파일 끝의 ts 를 읽어 그보다 뒤(ts > last)만 조회해 덧붙인다. DB 조회 범위도 같이
    좁아져서 하루가 길어져도 표본당 비용이 일정하다 (2026-08-05).
    """
    if not DB_PATH.exists():
        return
    path = out_dir / f"lp_eval_ts_{trade_date}.csv"
    after = _csv_append_state(path, _TS_CSV_HEADER)
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        _log(f"ts csv open failed: {exc!r}")
        return
    where = "WHERE trade_date=?" + ("" if after is None else " AND ts>?")
    params = (trade_date,) if after is None else (trade_date, after)
    rows: dict = {}   # (ts, code) -> 행 dict
    try:
        for ts, code, b, tick, bp, price in con.execute(
            f"SELECT ts, code, basis, tick, bp, price FROM lp_spread_ts {where}", params
        ):
            r = rows.setdefault((ts, code), {"price": None})
            if price is not None:
                r["price"] = price
            r[f"{b}_tick"] = tick
            r[f"{b}_bp"] = None if bp is None else round(bp, 2)
        for ts, code, actual, intraday in con.execute(
            f"SELECT ts, code, actual_dev, intraday_dev FROM lp_dev_ts {where}", params
        ):
            r = rows.get((ts, code))
            if r is None:
                continue
            r["actual_dev"] = None if actual is None else round(actual, 4)
            r["intraday_dev"] = None if intraday is None else round(intraday, 4)
    except sqlite3.Error as exc:
        _log(f"ts csv query failed: {exc!r}")
        con.close()
        return
    con.close()
    _csv_append(path, _rows_to_csv(rows, names, trade_date))


def _write_pre_csv(out_dir: Path, names: dict, trade_date: str) -> None:
    """개장 직후(09:00~09:05) 표본을 별도 CSV 에 이어쓴다.

    컬럼은 본장 시계열 CSV(_TS_CSV_HEADER)와 동일해서 두 파일을 그대로 이어붙여
    비교할 수 있다. 파일을 나눈 건 본장 CSV 를 읽는 쪽이 의무 면제 구간을 모르고
    섞어 쓰는 사고를 막으려는 것 (2026-08-04). 이어쓰기 규칙은 본장 CSV 와 같다 —
    09:05 이후로는 새 행이 없어 매 표본마다 파일 꼬리만 읽고 끝난다.
    """
    if not DB_PATH.exists():
        return
    path = out_dir / f"lp_eval_pre_{trade_date}.csv"
    after = _csv_append_state(path, _TS_CSV_HEADER)
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        _log(f"pre csv open failed: {exc!r}")
        return
    where = "WHERE trade_date=?" + ("" if after is None else " AND ts>?")
    params = (trade_date,) if after is None else (trade_date, after)
    rows: dict = {}
    try:
        for ts, code, b, tick, bp, price, actual, intraday in con.execute(
            "SELECT ts, code, basis, tick, bp, price, actual_dev, intraday_dev "
            f"FROM lp_pre_ts {where}", params,
        ):
            r = rows.setdefault((ts, code), {"price": None})
            if price is not None:
                r["price"] = price
            r[f"{b}_tick"] = tick
            r[f"{b}_bp"] = None if bp is None else round(bp, 2)
            r["actual_dev"] = None if actual is None else round(actual, 4)
            r["intraday_dev"] = None if intraday is None else round(intraday, 4)
    except sqlite3.Error as exc:
        # 테이블 미생성(첫 개장 전) 등 — 조용히 넘긴다.
        _log(f"pre csv query skipped: {exc!r}")
        con.close()
        return
    con.close()
    _csv_append(path, _rows_to_csv(rows, names, trade_date))


def write_daily_snapshot(names: dict | None = None) -> bool:
    """오늘치 JSON + 분단위 시계열 CSV + 개장직후 CSV + 전기간 마스터 CSV 를 S:
    출력폴더에 덮어쓴다. 폴더가 없으면 조용히 skip(로컬·마운트 부재). 파일별로 예외를
    삼켜 한쪽이 잠겨도(예: Excel 로 CSV 오픈 중) 다른 쪽 저장은 진행한다."""
    out_dir = LP_EVAL_OUT_DIR
    if not out_dir.is_dir():
        return False
    names = names or {}
    today = datetime.now(_KST).strftime("%Y-%m-%d")
    ok = True
    try:
        _write_pre_csv(out_dir, names, today)
    except OSError as exc:
        _log(f"pre csv write failed: {exc!r}")
        ok = False
    # 본장 표본이 아직 없는 시각(09:00~09:05)에는 일별 JSON·마스터 CSV 를 건드리지
    # 않는다 — 빈 껍데기로 덮어써 봐야 09:06 에 다시 채워질 뿐이다.
    snap = build_lp_eval(today, names)
    if not any(b.get("total_min") for e in snap["etfs"] for b in e["basis"].values()):
        return ok
    try:
        tmp = out_dir / f"lp_eval_{today}.json.tmp"
        tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(out_dir / f"lp_eval_{today}.json")
    except OSError as exc:
        _log(f"daily json write failed: {exc!r}")
        ok = False
    try:
        _write_ts_csv(out_dir, names, today)
    except OSError as exc:
        _log(f"ts csv write failed: {exc!r}")
        ok = False
    try:
        _write_master_csv(out_dir, names)
    except OSError as exc:
        _log(f"master csv write failed: {exc!r}")
        ok = False
    return ok
