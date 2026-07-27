"""지수 롤링 윈도우 통계 — INDEX_MONITOR.db(분단위 index_ticks) 판독 (2026-07-23).

CHECK 에이전트가 ``/srv/legacy/db/INDEX_MONITOR.db`` 에 분단위로 적재하는 지수
등락률(change_pct)을 읽어, 지수별 '최근 60분 변동폭(max−min)' 등을 계산한다.
대시보드 우측 상단 알림 팝업의 트리거② (60분 롤링 max−min ≥ 2%p) 판정용.

네트워크(SMB) DB 를 직접 열면 크로스머신 writer 와 잠금 충돌이 나므로, 레거시
관례(legacy_inputs.sync_db)대로 writable 캐시(/app/.cache)로 복사한 뒤 read-only 로
읽는다. 복사(6.7MB SMB 읽기 ~1초+)를 요청 경로에서 하면 api 프록시 2초 예산을
넘길 수 있으므로 **백그라운드 스레드로 비동기 갱신**하고, 요청은 항상 로컬 캐시만
읽어 즉시 응답한다(캐시는 named volume 이라 재기동에도 유지). 임시파일→원자적 교체
(os.replace)로 동시 읽기 중 torn read 를 막는다. (INDEX_MONITOR.db 는 -wal 없음 =
rollback-journal 모드라 .db 단독 복사로 완전함.)

순수 판독 — 예외 시 가능한 만큼만 반환(indices 빈 리스트 가능).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from collector.legacy_inputs import CACHE_DIR, LEGACY_DB, ensure_dirs

_KST = timezone(timedelta(hours=9))

SRC_DB = LEGACY_DB / "INDEX_MONITOR.db"
DEST_DB = CACHE_DIR / "index_monitor.db"

# 대상 지수(코드→표시명). CHECK 코드계: KOSPI/KOSDAQ/NQ_FUT.
DEFAULT_CODES = ("KOSPI", "KOSDAQ", "NQ_FUT")
DISPLAY = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "NQ_FUT": "나스닥 선물"}

WINDOW_MIN = 60  # max−min 을 보는 롤링 창
BUFFER_MIN = 90  # DB 에서 끌어오는 범위(창보다 넓게 — 여유/사후용)
RESET_FROM_PCT = 1.0  # 세션 리셋 감지 — 직전 |등락률|≥이 값이며 지금 0 이면 리셋으로 봄
_REFRESH_S = 15.0  # 로컬 캐시 백그라운드 갱신 최소 간격

# ── 하루 알림 로그(서버측) 파라미터 — 프론트 트리거와 동일 의미를 서버에서 재현 ──
# 알림을 서버가 하루 이력에서 계산·보관하므로, 어느 브라우저가 언제 켜져 있었든
# 모든 클라이언트가 동일한 목록을 본다(늦게 접속해도 소급 표시).
ALERT_FIRE_PCT = 2.0   # 60분 변동폭(max−min) ≥ 2%p 발화
ALERT_REARM_PCT = 1.5  # <1.5%p 로 줄면 재무장(연속 발화 방지)
ACC_START_MIN = 8 * 60 + 55  # 08:55 KST 부터 누적
ACC_END_MIN = 16 * 60        # 16:00 까지
OPEN_LO_MIN = 9 * 60 + 5     # 09:05~09:08 장초반(전일比) 1회
OPEN_HI_MIN = 9 * 60 + 8
_ALERTS_TTL_S = 15.0  # 하루 스캔 재계산 최소 간격(요청마다 재계산 방지)

_last_refresh_ts = 0.0
_copy_lock = threading.Lock()  # 동시에 하나의 복사만
_alerts_cache: list | None = None
_alerts_ts = 0.0


def _log(msg: str) -> None:
    print(f"[index-window] {msg}", file=sys.stderr, flush=True)


def _is_zero(p) -> bool:
    """등락률이 사실상 0 (장전/휴장 평탄 0 판정용). 장마감 후 익일 개장 전까지
    등락률은 정확히 0 으로 유지된다."""
    return p is not None and abs(p) < 1e-9


def _copy_db() -> None:
    if not SRC_DB.exists():
        _log(f"source DB absent: {SRC_DB}")
        return
    try:
        ensure_dirs()
        tmp = DEST_DB.with_name(DEST_DB.name + ".tmp")
        shutil.copyfile(SRC_DB, tmp)
        os.replace(tmp, DEST_DB)  # 원자적 교체 — 읽는 중이어도 안전(Linux)
    except OSError as exc:
        _log(f"copy failed: {exc!r}")


def _maybe_refresh_async() -> None:
    """캐시가 오래됐고 복사가 진행 중이 아니면 백그라운드 스레드로 복사.
    요청 경로를 절대 블로킹하지 않는다(첫 복사 전엔 빈 결과가 나올 수 있음)."""
    global _last_refresh_ts
    now = time.time()
    if now - _last_refresh_ts < _REFRESH_S:
        return
    if not _copy_lock.acquire(blocking=False):
        return  # 이미 복사 중
    _last_refresh_ts = now

    def _run() -> None:
        try:
            _copy_db()
        finally:
            _copy_lock.release()

    threading.Thread(target=_run, daemon=True).start()


def _clean_window(rows, win_from: str):
    """rows(전체, observed_at 오름차순) → 창 [win_from..] 에서 0-리셋/trade_date 컷 정리.

    r = (observed_at, change_pct, price, trade_date). 장 마감후 유지값→익일 0 불연속,
    장전/휴장 연속 0 을 잘라 가짜 변동을 없앤다(build_index_window 와 동일 규칙).
    """
    win = [r for r in rows if r[0] >= win_from and r[1] is not None]
    if win:
        cut = 0
        for i in range(1, len(win)):
            reset = abs(win[i - 1][1]) >= RESET_FROM_PCT and _is_zero(win[i][1])
            td_changed = win[i - 1][3] != win[i][3]
            if reset or td_changed:
                cut = i
        win = win[cut:]
        j = 0
        while j < len(win) and _is_zero(win[j][1]):
            j += 1
        win = win[j:]
    return win


def _extremes(win):
    """정리된 창의 극값·변동폭·방향. win 은 observed_at 오름차순, 동값이면 이른 시각."""
    if not win:
        return None
    mx = max(win, key=lambda r: r[1])  # (observed_at, pct, price, td)
    mn = min(win, key=lambda r: r[1])
    return {
        "max_pct": mx[1], "min_pct": mn[1], "max_at": mx[0], "min_at": mn[0],
        "spread": mx[1] - mn[1], "rose": mn[0] <= mx[0],
    }


def build_index_window(
    codes=DEFAULT_CODES, window_min: int = WINDOW_MIN, buffer_min: int = BUFFER_MIN
) -> dict:
    """지수별 최근 window_min 분 change_pct 변동폭(max−min) 등 통계.

    반환::

        { "generated_at": "YYYY-MM-DD HH:MM:SS",  # KST
          "window_min": 60,
          "indices": [ { "code","name","latest_at","latest_age_s","latest_pct",
                         "latest_price","max_pct","min_pct","spread_pct","n" }, ... ] }

    조회 실패/데이터 없음이면 indices 는 가능한 만큼만.
    """
    _maybe_refresh_async()  # 로컬 캐시 갱신은 백그라운드에서 (요청은 캐시만 읽음)

    now = datetime.now(_KST)
    gen = now.strftime("%Y-%m-%d %H:%M:%S")
    win_from = (now - timedelta(minutes=window_min)).strftime("%Y-%m-%d %H:%M:%S")
    buf_from = (now - timedelta(minutes=buffer_min)).strftime("%Y-%m-%d %H:%M:%S")

    out: dict = {"generated_at": gen, "window_min": window_min, "indices": []}
    if not DEST_DB.exists():
        return out  # 첫 백그라운드 복사 전 — 빈 결과(다음 폴링에 채워짐)
    try:
        con = sqlite3.connect(f"file:{DEST_DB}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        _log(f"open failed: {exc!r}")
        return out
    try:
        cur = con.cursor()
        for code in codes:
            try:
                rows = cur.execute(
                    "SELECT observed_at, change_pct, price, trade_date "
                    "FROM index_ticks "
                    "WHERE index_code=? AND observed_at>=? ORDER BY observed_at",
                    (code, buf_from),
                ).fetchall()
            except sqlite3.Error as exc:
                _log(f"query {code} failed: {exc!r}")
                continue
            if not rows:
                continue
            latest_at, latest_pct, latest_price, _latest_td = rows[-1]
            age = None
            try:
                lt = datetime.strptime(latest_at, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=_KST
                )
                age = (now - lt).total_seconds()
            except (ValueError, TypeError):
                age = None
            win = _clean_window(rows, win_from)
            entry = {
                "code": code,
                "name": DISPLAY.get(code, code),
                "latest_at": latest_at,
                "latest_age_s": age,
                "latest_pct": latest_pct,
                "latest_price": latest_price,
                "n": len(win),
                "max_pct": None,
                "min_pct": None,
                "max_at": None,
                "min_at": None,
                "spread_pct": None,
                "rose": None,
            }
            ext = _extremes(win)
            if ext:
                entry["max_pct"] = ext["max_pct"]
                entry["min_pct"] = ext["min_pct"]
                entry["max_at"] = ext["max_at"]
                entry["min_at"] = ext["min_at"]
                entry["spread_pct"] = ext["spread"]
                entry["rose"] = ext["rose"]
            out["indices"].append(entry)
    finally:
        con.close()
    return out


def build_index_alerts(codes=DEFAULT_CODES) -> dict:
    """오늘(KST) 발화한 지수 급등락 알림의 서버측 하루 로그(최신 우선).

    INDEX_MONITOR 전일 이력을 스캔해 프론트 트리거와 동일한 판정을 서버에서 재현한다:
      · roll1h — 08:55~16:00 표본마다 60분 변동폭(정리된 창 max−min)을 보고, ≥2%p 이면
        발화·비무장, <1.5%p 로 줄면 재무장(히스테리시스). 같은 스윙은 1회만.
      · open5 — 09:05~09:08 첫 표본의 전일比 등락률, 지수당 1회.
    ~15초 TTL 캐시(요청마다 재스캔 방지). 반환 alert:
      {id, code, label, kind, changePct, spreadPct, rose, maxAt, minAt, price, at(epoch ms)}
    """
    global _alerts_cache, _alerts_ts
    _maybe_refresh_async()
    now = datetime.now(_KST)
    gen = now.strftime("%Y-%m-%d %H:%M:%S")
    if _alerts_cache is not None and time.time() - _alerts_ts < _ALERTS_TTL_S:
        return {"generatedAt": gen, "alerts": _alerts_cache}

    day0 = now.strftime("%Y-%m-%d") + " 00:00:00"
    alerts: list = []
    if DEST_DB.exists():
        try:
            con = sqlite3.connect(f"file:{DEST_DB}?mode=ro", uri=True, timeout=2.0)
        except sqlite3.Error as exc:
            _log(f"alerts open failed: {exc!r}")
            con = None
        if con is not None:
            try:
                cur = con.cursor()
                for code in codes:
                    try:
                        rows = cur.execute(
                            "SELECT observed_at, change_pct, price, trade_date "
                            "FROM index_ticks WHERE index_code=? AND observed_at>=? "
                            "ORDER BY observed_at",
                            (code, day0),
                        ).fetchall()
                    except sqlite3.Error as exc:
                        _log(f"alerts query {code} failed: {exc!r}")
                        continue
                    if not rows:
                        continue
                    label = DISPLAY.get(code, code)
                    try:
                        dts = [datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") for r in rows]
                    except (ValueError, TypeError):
                        continue

                    # ── open5 (전일比 장초반, 지수당 1회) ──
                    for r, dt in zip(rows, dts):
                        if r[1] is None:
                            continue
                        m = dt.hour * 60 + dt.minute
                        if OPEN_LO_MIN <= m <= OPEN_HI_MIN:
                            alerts.append({
                                "id": f"open5:{code}:{r[0]}", "code": code, "label": label,
                                "kind": "open5", "changePct": r[1], "spreadPct": None,
                                "rose": None, "maxAt": None, "minAt": None,
                                "price": r[2], "at": int(dt.replace(tzinfo=_KST).timestamp() * 1000),
                            })
                            break

                    # ── roll1h (60분 변동폭 크로싱, 히스테리시스) ──
                    # 발화 후 같은 스윙(비무장 구간)이 더 커지면 그 에피소드의 **피크
                    # 변동폭**으로 갱신한다 — 첫 크로싱 값(예 2.05%p)이 아니라 실제 스윙의
                    # 최대(예 3.52%p)를 보여줘 브라우저별 관측 시점차와 무관하게 일관.
                    armed = True
                    episode = None  # 현재 발화 에피소드(비무장 중) — 피크 갱신 대상
                    lo = 0
                    for idx, (r, dt) in enumerate(zip(rows, dts)):
                        # 창 [t-60분, t] 유지 (two-pointer)
                        while lo < idx and (dt - dts[lo]).total_seconds() > WINDOW_MIN * 60:
                            lo += 1
                        m = dt.hour * 60 + dt.minute
                        if not (ACC_START_MIN <= m <= ACC_END_MIN):
                            continue
                        win = _clean_window(rows[lo:idx + 1], "")  # 이미 60분 창 → win_from 무의미
                        ext = _extremes(win)
                        if ext is None:
                            continue
                        if ext["spread"] >= ALERT_FIRE_PCT:
                            if armed:
                                armed = False
                                episode = {
                                    "id": f"roll1h:{code}:{r[0]}", "code": code, "label": label,
                                    "kind": "roll1h", "changePct": r[1],
                                    "spreadPct": ext["spread"], "rose": ext["rose"],
                                    "maxAt": ext["max_at"], "minAt": ext["min_at"],
                                    "price": r[2], "at": int(dt.replace(tzinfo=_KST).timestamp() * 1000),
                                }
                                alerts.append(episode)  # 참조 저장 — 아래에서 in-place 갱신
                            elif episode is not None and ext["spread"] > episode["spreadPct"]:
                                episode["spreadPct"] = ext["spread"]
                                episode["rose"] = ext["rose"]
                                episode["maxAt"] = ext["max_at"]
                                episode["minAt"] = ext["min_at"]
                                episode["changePct"] = r[1]
                                episode["price"] = r[2]
                        elif ext["spread"] < ALERT_REARM_PCT:
                            armed = True
                            episode = None
            finally:
                con.close()

    alerts.sort(key=lambda a: a["at"], reverse=True)
    _alerts_cache = alerts
    _alerts_ts = time.time()
    return {"generatedAt": gen, "alerts": alerts}
