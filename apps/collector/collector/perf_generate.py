"""[성과보고] 성과분석 HTML 자동 생성 (2026-08-11 신설).

사람이 `비교PORT_분석.bat` · `전기차PORT_분석.bat` 을 돌리던 자리를 대신한다. n8n 이
아침에 여러 번 부르고, 실행 여부는 **시각이 아니라 소스의 신선도**로 정한다.

━━ 왜 시각 트리거가 아닌가 ━━
소스 워크북은 블룸버그 BDH 수식이라 엑셀 + 단말이 있는 Windows PC 에서 사람이 열어야
새 종가가 들어온다. 실제 저장 시각이 07:5x ~ 09:4x 로 흔들려서 "08:30 에 실행" 은
조용히 전날 숫자로 보고서를 만든다. 도착을 기다리는 구조여야 한다.

━━ 게이트 ━━
    Price 시트 마지막 영업일  >  이미 만든 같은 보고서의 최신 기준일   → 만든다

`port_engine` 이 기준일을 정할 때 쓰는 값(`S["dates"][-1]`)을 그대로 본다. 덕분에

    · 휴장일엔 시트가 안 늘어나 저절로 건너뛴다 — 휴장일 캘린더가 필요 없다
    · 하루에 몇 번을 불러도 첫 성공 뒤엔 전부 건너뛴다 — 멱등
    · 소스가 늦게 와도 다음 호출이 잡는다

전기차 스냅샷은 시트에 **날짜가 없다**. 기준일이 곧 '오늘' 이라 비교할 축이 없고, 파일
mtime 이 유일한 신선도 신호다. 두 대상의 게이트가 다른 이유다.

━━ 알림 정책은 여기 없다 ━━
"언제 포기하고 알릴지" 는 n8n 이 정한다. 여기서는 사실만 돌려준다(`status` ·
`sourceStale` · `priceLastDate` · `prevAsOf`). 정책을 코드에 박으면 문구 하나 바꾸는 데도
컨테이너를 다시 띄워야 한다.

━━ 쓰기 범위 ━━
마운트는 `:ro` 가 원칙이고 `output/` 과 `funds/` 두 곳만 `:rw` 로 겹쳐 걸었다. 이 모듈이
건드리는 것도 그 둘뿐이다. 입력(input/)·엔진(분석엔진/)은 절대 쓰지 않는다.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from datetime import date, datetime

from collector import perf_report as _pr

PERF_REPORT_ROOT = _pr.PERF_REPORT_ROOT

# 파일명 규약에서 나오는 `who`. `perf_report._classify` 가 `A_B_비교보고서_...` 를
# "A vs B" 로 풀어 주므로 그 형태로 맞춰 둔다. 게이트가 "이미 만든 것"을 찾는 열쇠다.
WRAP_WHO = "AI코어테크 vs TORUS"
WRAP_MAIN = "aicoretech"
WRAP_BM = "torus"

# 전기차는 스냅샷 소스가 하나뿐이고 BM 비중이 같은 시트에 있다. 시트 이름이 곧 펀드명.
EV_FILE = "05M72_port.xlsx"

# `port_engine.PERIODS` 와 같은 표기. 파일명·머리말에 그대로 박힌다.
SCOPES = {"일간": "daily", "주간": "weekly", "월간": "monthly"}

_ENGINE = None


def _engine():
    """엔진 모듈 3종. 마운트 경로에서 **그대로** 임포트한다.

    S: 의 엔진이 정본이다. 컨테이너에 복사본을 두면 원본과 갈라져 어느 쪽이 도는지 알 수
    없게 된다. sys.path 에 얹기만 하고 코드는 건드리지 않는다.

    ⚠️ 단 **한 프로세스에 한 번만** 임포트된다(파이썬 모듈 캐시). S: 의 엔진을 고쳐도
    이미 떠 있는 collector 는 옛 코드로 계속 돈다. 엔진을 손봤으면
    `docker compose --profile collector restart collector` 를 해야 반영된다.
    매 호출 reload 는 하지 않는다 — 보고서를 만드는 도중에 코드가 바뀌면 같은 산출물
    안에서 로직이 섞인다.
    """
    global _ENGINE
    if _ENGINE is None:
        eng = os.path.join(PERF_REPORT_ROOT, "분석엔진")
        if eng not in sys.path:
            sys.path.insert(0, eng)
        import compare_report
        import port_engine
        import snapshot_report
        _ENGINE = (port_engine, compare_report, snapshot_report)
    return _ENGINE


def _saved_at(path: str) -> tuple[str | None, bool]:
    """(저장 시각 'YYYY-MM-DD HH:MM', 오늘 저장이 아닌가). 파일이 없으면 (None, True)."""
    try:
        m = datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None, True
    return m.strftime("%Y-%m-%d %H:%M"), m.date() != date.today()


def _prev_as_of(who: str, scope: str) -> str | None:
    """이미 만들어 둔 같은 보고서의 최신 기준일. 없으면 None.

    `perf_report._scan()` 을 그대로 쓴다. 파일명이 계약이라는 규약이 이미 거기 있고,
    게이트가 따로 규약을 흉내 내면 둘이 어긋나는 순간 매일 중복 생성된다.
    """
    best = None
    for it in _pr._scan():
        if it["kind"] != "compare" or it["scope"] != scope or it["who"] != who:
            continue
        if best is None or it["asOf"] > best:
            best = it["asOf"]
    return best


def _write(out_dir, name: str, html: str) -> str:
    """보고서 저장. 돌려주는 값은 마운트 루트 기준 상대경로(대시보드가 쓰는 `rel`).

    `out_dir` 는 `E.output_dir()` 이 만들어 준 `output\\{생성일}\\` 이다. 묶는 기준이
    기준일이 아니라 만든 날이라, 기준일이 며칠 밀린 보고서도 오늘 폴더에 들어간다.
    """
    (out_dir / name).write_text(html, encoding="utf-8")
    return f"output/{out_dir.name}/{name}"


# ═══════════════════════════════════════════════════════════
#  대상 1 — 랩 비교 (AI코어테크 vs TORUS)
# ═══════════════════════════════════════════════════════════

def _run_wrap(kind: str, scope: str, force: bool) -> dict:
    E, CMP, _ = _engine()
    src = os.path.join(PERF_REPORT_ROOT, "input", E.WRAP_FILE)
    saved_at, stale = _saved_at(src)

    # 게이트용으로 한 번, `E.run` 이 안에서 또 한 번 워크북을 연다. 300KB 를 SMB 로 두 번
    # 읽는 왕복이 붙지만, 엔진의 적재 경로를 흉내 내지 않는 편이 어긋날 자리가 없다.
    S = E.load_source()
    try:
        last = S["dates"][-1]
    finally:
        S["wb"].close()

    prev = _prev_as_of(WRAP_WHO, scope)
    base = {"target": "wrap", "label": WRAP_WHO, "scope": scope,
            "priceLastDate": last, "prevAsOf": prev,
            "sourceSavedAt": saved_at, "sourceStale": stale}

    if not force and prev is not None and last <= prev:
        return {**base, "status": "skip", "asOf": prev, "file": None,
                "reason": f"이미 최신 — 기준일 {prev} 보고서가 있습니다"}

    R = E.run([WRAP_MAIN, WRAP_BM], last, kind, bm_key=WRAP_BM)
    html, name = CMP.build(R)
    rel = _write(E.output_dir(), name, html)

    per, main = R["period"], R["ports"][0]
    return {**base, "status": "ok", "asOf": R["as_of"], "file": rel, "name": name,
            "reason": f'새 종가 {last} — {per["start"]} → {per["end"]} 로 생성',
            "period": f'{per["start"]} → {per["end"]}',
            "totalPct": round(main["returns"]["total"] * 100, 4),
            "vsBmBp": None if main["vs_bm_bp"] is None else round(main["vs_bm_bp"], 1),
            "qa": R["qa"]}


# ═══════════════════════════════════════════════════════════
#  대상 2 — 전기차 스냅샷 (글로벌전기차펀드 vs BM)
# ═══════════════════════════════════════════════════════════

def _run_ev(kind: str, scope: str, force: bool) -> dict:
    E, _, SNAP = _engine()
    src = os.path.join(PERF_REPORT_ROOT, "input", EV_FILE)
    saved_at, stale = _saved_at(src)
    today = date.today().isoformat()

    # 시트에 날짜가 없다. 기준일은 '오늘' 이라는 딱지일 뿐이라, 소스가 오늘 저장된 것이
    # 아니면 어제 숫자에 오늘 날짜를 붙이는 꼴이 된다. 그래서 mtime 이 곧 게이트다.
    base = {"target": "ev", "label": "글로벌전기차펀드 vs BM", "scope": scope,
            "priceLastDate": None, "sourceSavedAt": saved_at, "sourceStale": stale}

    items = [s for s in SNAP.discover(skip={E.WRAP_FILE}) if s["file"] == EV_FILE]
    if not items:
        return {**base, "status": "error", "asOf": None, "file": None, "prevAsOf": None,
                "reason": f"{EV_FILE} 이 스냅샷으로 인식되지 않습니다 "
                          f"(시트 합계가 종목 합과 어긋나거나 열 배치가 바뀜)"}
    item = items[0]
    who = f'{item["short"]} vs BM'
    prev = _prev_as_of(who, scope)
    base = {**base, "label": who, "prevAsOf": prev}

    if not force and prev is not None and prev >= today:
        return {**base, "status": "skip", "asOf": prev, "file": None,
                "reason": f"이미 최신 — 기준일 {prev} 보고서가 있습니다"}
    if not force and stale:
        return {**base, "status": "skip", "asOf": None, "file": None,
                "reason": f"소스 미갱신 — {EV_FILE} 이 {saved_at} 저장본입니다"}

    D = SNAP.analyze(item["src"], today, kind, scope, item["label"], item["short"])
    html, name = SNAP.build(D)
    rel = _write(E.output_dir(), name, html)
    return {**base, "status": "ok", "asOf": today, "file": rel, "name": name,
            "reason": f"소스 {saved_at} 저장 — 기준일 {today} 로 생성",
            "totalPct": round(D["main"]["returns"]["total"] * 100, 4),
            "vsBmBp": round(D["excess_bp"], 1), "qa": D["qa"]}


# ═══════════════════════════════════════════════════════════

def _refresh_fund_series() -> dict:
    """대시보드 [누적 수익률 비교] 그래프의 시계열(`funds/*.json`).

    `analyze_cli` 가 보고서를 만든 뒤 곁들여 부르던 것과 같다. 소스가 같은 엑셀이라 따로
    스케줄할 이유가 없고, 1초짜리이며 claude 를 부르지 않는다.
    """
    _engine()                       # sys.path 에 엔진 경로를 얹는다
    import build_funds
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = build_funds.main(quiet=True)
    except Exception as exc:        # noqa: BLE001  보고서는 이미 나왔다. 여기서 안 죽는다
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    return {"status": "ok" if rc == 0 else "error",
            "log": [l for l in buf.getvalue().splitlines() if l.strip()][-6:]}


def generate(scope: str = "일간", force: bool = False) -> dict:
    """두 보고서를 신선도 게이트에 걸어 생성한다.

    scope  일간 · 주간 · 월간. 파일명과 머리말에 그대로 박힌다.
    force  게이트를 무시하고 무조건 만든다. 수동 재생성용이며 스케줄은 쓰지 않는다.

    한 대상이 실패해도 다른 대상은 만든다. 둘은 소스도 엔진 경로도 달라서 같이 죽을
    이유가 없다.
    """
    kind = SCOPES.get(scope)
    if kind is None:
        raise ValueError(f"scope 는 {' · '.join(SCOPES)} 중 하나여야 합니다: {scope!r}")

    results = []
    for fn in (_run_wrap, _run_ev):
        try:
            results.append(fn(kind, scope, force))
        except Exception as exc:                              # noqa: BLE001
            results.append({"target": fn.__name__[5:], "scope": scope, "status": "error",
                            "asOf": None, "file": None,
                            "reason": f"{type(exc).__name__}: {exc}"})

    ran = any(r["status"] == "ok" for r in results)
    return {
        "today": date.today().isoformat(),
        "scope": scope,
        "ran": ran,
        # 하나라도 소스가 안 온 게 있으면 n8n 이 마지막 발화에서 이걸 보고 알린다.
        "sourceStale": any(r.get("sourceStale") for r in results),
        "results": results,
        "fundSeries": _refresh_fund_series() if ran else {"status": "skip"},
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
