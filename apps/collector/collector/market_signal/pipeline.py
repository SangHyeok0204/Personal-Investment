# -*- coding: utf-8 -*-
r"""[시장 시그널] 파이프라인 오케스트레이터 — 1단→2단→3단→카드 (2026-08-31 신설).

    price_monitor.xlsx
        │
        ├─ 1단 signal_rules.detect_all   "튀었다"        (하루 8.6건)
        ├─ 2단 graph.interpret            "왜 튀었나"     (묶음 접기 → 가설)
        ├─ 3단 news.gather                "근거가 있나"   (Google RSS, 48h)
        └─ 카드 payload                    [자산군] 시그널 감지 : 15자 요약

★★**AI 없이도 완결된다.** 2단이 내는 `summary`("암호화폐 전반 강세" = 9자)가 이미
  사용자가 요구한 "15자 내외 요약"이다. LLM 은 문장을 예쁘게 다듬을 뿐 판단을 하지
  않는다 — 판단은 결정론 엔진(1단)과 그래프(2단)가 이미 끝냈다.
  그래서 이 파이프라인은 컨테이너 안에서 **전부** 돌고, AI 윤문은 나중에 얹는
  선택지로 남긴다([[claude-cli-subprocess-bridge]] 패턴). 그렇게 하면 claude 가 없는
  컨테이너 제약이 **크리티컬 패스에서 빠진다**.

★뉴스는 상위 후보 몇 개에만 건다(NEWS_TOP). 가설 9건에 전부 걸면 쿼리 27개라
  요청이 20초를 넘긴다 — 카드는 어차피 1건만 보여준다.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

NEWS_TOP = 3           # 뉴스를 실제로 조회할 상위 가설 수
CARD_MAX = 3           # payload 에 담을 카드 항목 수(화면은 1~2건만 보여준다)

# 전일에도 떴던 가설의 severity·confidence 에 곱할 값.
# ★0 이 아닌 이유 = **지우면 안 되기 때문이다.** MtD 기준 시그널은 원래 며칠씩 이어지는
#   게 정상이고, 사흘째 이어지는 추세도 사실이다. 다만 '오늘 새로 생긴 것'이 먼저
#   보여야 해서 아래로 내리기만 한다(주간가격모니터 anomaly_rules.REPEAT_PENALTY 와 같은 값).
# ★실측 근거(2026-08-31 백테스트, 14일 표본): **3일 간격 표본인데도 직전 표본일과
#   평균 1.5건/일이 겹쳤다.** 연속일이면 더 심하다 — 억제가 없으면 카드가 며칠씩 고인다.
REPEAT_PENALTY = 0.45


def _prev_business_day(d: date) -> date:
    """직전 영업일(토·일 건너뜀). 공휴일은 무시한다 — 그날 값이 없으면 시트가
    ffill 이라 시그널이 안 나고, 그러면 신규성 판정이 '전부 신규'로 떨어질 뿐이다."""
    p = d - timedelta(days=1)
    while p.weekday() >= 5:
        p -= timedelta(days=1)
    return p

ASSET_LABEL = {"equity": "주식", "bond": "채권", "commodity": "원자재",
               "fx": "환", "crypto": "비트코인"}


# ── 카드 문구 조립 (수치 중심) ────────────────────────────────────────────────
# 사용자 지정 형식(2026-09-01):
#     [시그널 시기]
#     [자산군] [하위분류] [무엇] [수치][단위] [동사]
#     - (추가 간단설명)
# 예)  26-09-01
#      미국채 10Y 시장금리 4.75% 달성
# 예)  25-09-01 ~ 26-09-01
#      원자재 탄산리튬 가격 xx% 상승
#
# ★★문구를 여기(collector)에서 만든다. 화면이 조립하면 숫자·단위·기간을 다시 계산해야
#   하는데, 그러면 카드 문구와 시그널 계산이 **다른 곳에서 두 번** 정의된다.
# ★★기간은 **그 룰이 실제로 잰 구간**이다. spike(wtd)면 7일, streak 면 연속 일수,
#   trend_flip 이면 크로스가 난 날. 아무 날짜나 찍으면 "언제 것인지"가 거짓이 된다.

def _d(iso: str) -> str:
    """YYYY-MM-DD → YY-MM-DD (카드가 좁다)."""
    return iso[2:]


def _span(asof: date, days: int) -> str:
    return f"{_d((asof - timedelta(days=days)).isoformat())} ~ {_d(asof.isoformat())}"


_SPIKE_DAYS = {"dtd": 1, "wtd": 7, "mtd": 30}


def _phrase(sig: dict, asset_label: str, n_markets: int,
            ind: dict | None = None) -> tuple[str, str, str]:
    """시그널 하나 → (시기, 본문, 부연). 본문이 카드의 큰 글씨다.

    ⚠️`sig` 는 2단이 접어 놓은 사본이라 **indicators 가 떨어져 있다**(graph._hyp 가
      payload 를 줄이려고 뺀다). 수치가 필요하므로 1단 원본의 지표를 따로 받는다.
    """
    m = ind or sig.get("indicators") or {}
    asof_s = m.get("asof") or sig.get("asof") or ""
    asof = date.fromisoformat(asof_s) if asof_s else date.today()
    lab = sig.get("label", "")
    yld = bool(sig.get("is_yield"))
    unit = "bp" if yld else "%"
    v = sig.get("value")
    rule = sig.get("rule")

    # 채권은 이름에 이미 국가가 들어 있어(미국채 10Y) 자산군을 덧붙이지 않는다.
    who = lab if yld else f"{asset_label} {lab}"
    extra = f"{n_markets}개 시장 동반" if n_markets > 1 else ""

    if rule == "spike":
        days = _SPIKE_DAYS.get(sig.get("metric"), 1)
        verb = "상승" if (v or 0) > 0 else "하락"
        what = "시장금리" if yld else "가격"
        body = f"{who} {what} {abs(v):.2f}{unit} {verb}"
        note = sig.get("note", "")
        tail = note.split("—")[-1].strip() if "—" in note else ""
        return _span(asof, days), body, " · ".join(x for x in (tail, extra) if x)

    if rule == "range_break":
        run = sig.get("run_days") or 0
        start = asof - timedelta(days=run)
        up = bool(sig.get("is_high"))
        if yld:
            body = f"{who} 시장금리 {m.get('price', 0):.2f}% {'달성' if up else '하회'}"
        else:
            gain = m.get("ytd_low_gain") if up else m.get("ytd_high_drawdown")
            body = (f"{who} 가격 52주 {'신고가' if up else '신저가'} 돌파"
                    + (f" (연{'저' if up else '고'}점 대비 {abs(gain):.1f}%)" if gain else ""))
        q = sig.get("quiet_days")
        sub = " · ".join(x for x in (f"{q}일 만의 돌파" if q else "",
                                     f"{run}일째 지속" if run else "", extra) if x)
        return _d(start.isoformat()), body, sub

    if rule == "trend_flip":
        cd = sig.get("cross_days") or 0
        when = asof - timedelta(days=abs(cd))
        body = f"{who} 20/60 이평 {'골든' if cd > 0 else '데드'}크로스"
        dev = m.get("dev60")
        return (_d(when.isoformat()), body,
                " · ".join(x for x in (f"60일선 대비 {dev:+.1f}{unit}" if dev is not None else "",
                                       extra) if x))

    if rule == "streak":
        st = int(sig.get("streak") or 0)
        w = m.get("wtd")
        body = (f"{who} {'시장금리' if yld else '가격'} {abs(st)}일 연속 "
                f"{'상승' if st > 0 else '하락'}")
        return (_span(asof, abs(st)), body,
                " · ".join(x for x in (f"주간 {w:+.2f}{unit}" if w is not None else "", extra) if x))

    if rule == "vol_regime":
        body = f"{who} 변동성 {(v or 0) / 100 + 1:.1f}배 확대"
        return _d(asof.isoformat()), body, extra

    return _d(asof.isoformat()), f"{who} {sig.get('note', '')}", extra


def _locator() -> dict:
    """티커 → (자산군, layer1, layer2). 화면이 카드를 눌렀을 때 **가운데 차트를
    어디로 옮길지** 정하는 좌표다.

    ★정본은 price_board.CATEGORIES 다 — 차트(PriceTreeCard/PriceMetricChartCard)가
      보는 분류와 **같은 표**를 써야 클릭이 실제로 그 시장에 가 닿는다.
    """
    from collector import price_board as pb
    out = {}
    for c in pb.CATEGORIES:
        for l1, l2, _label, _sub, ticker in c["rows"]:
            out[ticker] = (c["key"], l1, l2)
    return out


def _selection(signals: list[dict], loc: dict) -> dict | None:
    """카드 클릭 시 차트가 잡을 선택. 차트의 두 모드(leaf/group)를 그대로 따른다.

    ★시그널이 여럿이고 **전부 같은 묶음**이면 group 으로 잡는다 — "산업금속 전반 강세"
      를 눌렀는데 알루미늄 하나만 뜨면 카드가 한 말과 화면이 어긋난다.
    ★묶음이 갈리거나 1건이면 leaf.
    ⚠️**layer2 가 비어도 group 은 성립한다.** 원자재·채권은 계층이 한 겹이라 l2="" 인데
      (`("산업금속","",...)`), `build_group_series(cat,"산업금속","")` 가 6개 계열을
      정상으로 낸다(실측). 처음에 `l1 and l2` 로 막았다가 "산업금속 전반 강세"가
      알루미늄 하나로 떨어지는 걸 보고 고쳤다 — 트리 카드도 같은 규칙이다
      (Node.onClick 이 l2 를 빈 문자열로 넘긴다).
    """
    tk = [s.get("market") for s in signals if s.get("market") in loc]
    if not tk:
        return None
    cats = {loc[t][0] for t in tk}
    if len(cats) != 1:
        return {"cat": loc[tk[0]][0], "kind": "leaf", "key": tk[0]}
    cat = cats.pop()
    if len(tk) > 1:
        gs = {(loc[t][1], loc[t][2]) for t in tk}
        if len(gs) == 1:
            l1, l2 = gs.pop()
            if l1:
                return {"cat": cat, "kind": "group", "l1": l1, "l2": l2,
                        "label": l2 or l1}
    return {"cat": cat, "kind": "leaf", "key": tk[0]}


def _log(msg: str) -> None:
    print(f"[market-signal] {msg}", file=sys.stderr, flush=True)


def run(asof: date | None = None, with_news: bool = True,
        top: int = 999) -> dict:
    """전 단계를 돌려 카드 payload 를 만든다.

    반환::
        {"generated_at","asof","cards":[{...}],"stats":{...},"note":None}
    """
    from collector import price_board as pb
    from collector.market_signal import signal_rules as sr

    now = datetime.now(_KST)
    out: dict = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "asof": None,
        "cards": [],
        "stats": {},
        "note": None,
    }

    # ── 원천 ──
    try:
        cols = pb._read_columns()
    except FileNotFoundError:
        out["note"] = f"원천 파일이 없습니다 — {pb.SRC_PATH}"
        return out
    catalog = sr.catalog_from_price_board()

    # ── 1단 ──
    signals = sr.detect_all(cols, catalog, asof=asof, top=top)
    out["asof"] = signals[0]["indicators"]["asof"] if signals else None
    if not signals:
        out["note"] = "오늘은 임계를 넘은 시그널이 없습니다."
        out["stats"] = {"signals": 0, "hypotheses": 0, "news_checked": 0}
        return out

    # ── 2단 ──
    try:
        from collector.market_signal import graph as gr
        G = gr.Graph()
        # ★★**조용한 품질 저하를 막는다.** markets.ttl 이 없으면(첫 기동·볼륨 초기화)
        #   knowledge.ttl 만 실려 그래프에 **관측이 하나도 없다**. 그래도 예외는 안 나고
        #   가설은 만들어지는데, 이웃 값을 못 보니 전부 Idiosyncratic 으로 무너진다.
        #   카드는 멀쩡해 보이는데 판단은 근거가 없는 상태 — 가장 나쁜 실패다.
        #   → note 로 반드시 드러낸다(빈 payload + note 패턴, compute-index 카드 선례).
        if not G.ret:
            out["note"] = "관측 그래프(markets.ttl)가 아직 없습니다 — 해석 정확도가 낮습니다."
        hyps = gr.interpret(signals, G)
    except Exception as exc:  # noqa: BLE001
        # ★그래프가 죽어도 1단 결과는 살려 보낸다. 카드가 통째로 비는 것보다
        #   "튀었다"만이라도 띄우는 게 낫다(rdflib 미설치·ttl 손상 등).
        _log(f"graph stage failed, falling back to raw signals: {exc!r}")
        hyps = [{
            "hypothesis": "Raw", "priority": 1, "asset_class": s["asset_class"],
            "headline": s["label"], "summary": f"{s['label']} {s['note']}",
            "evidence": [], "confidence": 0.3, "severity": s["severity"],
            "signals": [{k: v for k, v in s.items() if k != "indicators"}],
        } for s in signals[:CARD_MAX]]
        out["note"] = "그래프 단계 실패 — 1단 결과만 표시합니다."

    # ── 신규성 — 전일에도 떴던 시그널은 순위를 내린다 ──
    #   ★★지우지 않고 **내리기만** 한다(주간가격모니터 선례 그대로). MtD 기준 시그널은
    #     원래 며칠씩 이어지는 게 정상이고, 사흘째 이어지는 추세도 사실이다. 다만
    #     '오늘 새로 생긴 것'이 먼저 보여야 한다.
    #   ★★**상태 파일을 쓰지 않고 전날을 그 자리에서 다시 판정한다.** 캐시로 하면
    #     과거 날짜로 다시 돌렸을 때 결과가 달라져 재현이 깨진다. 비용은 1단 한 번
    #     더(실측 ~3초) — 2단·3단은 안 돌린다(같은 시장·같은 룰이면 가설도 같다).
    try:
        prev = _prev_business_day(
            date.fromisoformat(out["asof"]) if out["asof"] else date.today())
        seen = {(s["market"], s["rule"]) for s in sr.detect_all(cols, catalog,
                                                               asof=prev, top=999)}
    except Exception as exc:  # noqa: BLE001
        _log(f"novelty check failed (skipping): {exc!r}")
        seen = set()
    for h in hyps:
        ss = h.get("signals") or []
        if ss and all((s.get("market"), s.get("rule")) in seen for s in ss):
            h["repeat"] = True
            h["severity"] = round(h["severity"] * REPEAT_PENALTY, 2)
            h["confidence"] = round(h["confidence"] * REPEAT_PENALTY, 2)
        else:
            h["repeat"] = False

    # ── 3단 (상위 후보만) ──
    n_news = 0
    if with_news:
        from collector.market_signal import news as nw
        for h in hyps[:NEWS_TOP]:
            try:
                h["news"] = nw.gather(h)
                n_news += 1
            except Exception as exc:  # noqa: BLE001
                _log(f"news stage failed for {h.get('headline')}: {exc!r}")
                h["news"] = {"supported": False, "score": 0.0, "articles": [],
                             "error": True}

    # ── 카드 ──
    #   ★근거가 확보된 가설을 **앞으로 올린다**(사용자 요구: "뒷받침되면 띄운다").
    #     다만 근거 없는 가설을 버리지는 않는다 — 뉴스가 늦게 붙는 사건이 많고,
    #     버리면 카드가 자주 빈다. supported 를 화면이 배지로 구분한다.
    def _rank(h):
        return (0 if (h.get("news") or {}).get("supported") else 1,
                1 if h.get("repeat") else 0,      # ★신규가 먼저
                -h["priority"], -h["confidence"], -h["severity"])

    hyps.sort(key=_rank)
    loc = _locator()
    ind_of = {x["market"]: x.get("indicators") for x in signals}   # 1단 원본 지표
    for h in hyps[:CARD_MAX]:
        nws = h.get("news") or {}
        prim = max(h["signals"], key=lambda x: x.get("severity", 0))
        per, line, lsub = _phrase(prim, ASSET_LABEL.get(h["asset_class"], ""),
                                  len(h["signals"]), ind_of.get(prim.get("market")))
        out["cards"].append({
            "asset_class": h["asset_class"],
            "asset_label": ASSET_LABEL.get(h["asset_class"], h["asset_class"]),
            "headline": h["headline"],
            "summary": h["summary"],               # ← 15자 내외
            "hypothesis": h["hypothesis"],
            "confidence": h["confidence"],
            "severity": h["severity"],
            "evidence": h["evidence"],
            "markets": [s["label"] for s in h["signals"]],
            # ★클릭 → 가운데 차트 이동에 쓰는 좌표. 표시명만으로는 차트가 시장을
            #   못 찾는다(차트 키는 블룸버그 티커다).
            "tickers": [s["market"] for s in h["signals"]],
            "sel": _selection(h["signals"], loc),
            "detail": [s["note"] for s in h["signals"]][:4],
            # ★수치 중심 3줄 문구(사용자 지정 2026-09-01). summary 는 2단 가설 문장으로
            #   그대로 두고(정렬·뉴스 검색이 쓴다) 화면 큰 글씨는 이쪽을 쓴다.
            "period": per, "line": line, "line_sub": lsub,
            "repeat": bool(h.get("repeat")),   # 전일에도 떴던 건인가
            "news_supported": bool(nws.get("supported")),
            "news_score": nws.get("score"),
            "articles": nws.get("articles", []),
        })

    out["stats"] = {
        "markets": len(catalog),
        "signals": len(signals),
        "hypotheses": len(hyps),
        "collapsed": len(signals) - len(hyps),
        "news_checked": n_news,
        "news_supported": sum(1 for h in hyps if (h.get("news") or {}).get("supported")),
        "repeats": sum(1 for h in hyps if h.get("repeat")),
    }
    return out


# ── markets.ttl 갱신 ────────────────────────────────────────────────────────
# ★1일 1회면 충분하다. 상관·체제는 하루 안에 의미 있게 안 변하는데, 매 요청마다
#   87×87 상관을 다시 재면 3.8초가 그냥 나간다.
_TTL_STAMP: dict = {"day": None}


def refresh_graph_if_stale(force: bool = False) -> dict | None:
    """markets.ttl 이 오늘 것이 아니면 다시 굽는다. 반환 = 요약 or None(스킵)."""
    from collector.market_signal import build_graph as bg

    # ★날짜가 바뀌었거나 **원천 시트가 갱신됐으면** 다시 굽는다. 상관·체제는 하루 안에
    #   의미 있게 안 변하지만, 시트에 새 날짜 행이 들어오면 그건 새 관측이다.
    stamp = (datetime.now(_KST).date(), _source_stamp())
    if not force and _TTL_STAMP["day"] == stamp and os.path.exists(bg_path()):
        return None
    try:
        info = bg.write(bg_path())
        _TTL_STAMP["day"] = stamp
        _log(f"markets.ttl rebuilt: {info['summary']}")
        return info
    except Exception as exc:  # noqa: BLE001
        _log(f"markets.ttl rebuild failed: {exc!r}")
        return None


def bg_path() -> str:
    from collector.market_signal import graph as gr
    return gr.MARKETS_TTL


# ── 매 정시 캐시 ────────────────────────────────────────────────────────────
# ★★사용자 요구가 "매 정시마다 (24시간 작동)"다. 그런데 화면 폴링은 10분이라 그대로
#   두면 시간당 6번 계산하고 **Google RSS 를 6번 때린다**(쿼리 3개 × 후보 3개 = 9콜).
#   정시 단위로 캐시하면 요구도 맞고 외부 호출도 1/6 로 준다.
# ★"정시에 미리 굽는" 별도 스케줄러를 두지 않는 이유: collector 는 이미 여러 lane 이
#   도는 프로세스라 잡을 하나 더 얹으면 기동 순서·실패 격리를 또 설계해야 한다.
#   **첫 요청이 그 시각의 계산을 하고 나머지는 캐시를 먹는** lazy 방식이면 같은 결과에
#   부품이 하나도 안 는다(us_stock_monitor 의 lazy 기동과 같은 idiom).
_CACHE: dict = {"key": None, "payload": None}


def _source_stamp() -> str:
    """원천 시트의 mtime+size. 갱신되면 값이 바뀐다.

    ★★2026-09-01 추가. 그 전에는 캐시 키가 시각뿐이라, 시트가 아침 7:41 에 갱신돼도
      08시대 첫 호출까지 **낡은 날짜(전일) 카드를 계속 내보냈다**. 원천이 바뀐 걸
      알면서 안 보는 캐시는 캐시가 아니라 지연이다.
    ★시트 갱신은 매 영업일 아침 ~7:45(가끔 오후 4시대에도) — 실측 백업 파일 패턴.
    """
    from collector import price_board as pb
    try:
        st = os.stat(pb.SRC_PATH)
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return "none"


def _hour_key(now: datetime | None = None) -> str:
    """캐시 키 = 시각 + **원천 스탬프**. 둘 중 하나만 바뀌어도 다시 계산한다."""
    n = now or datetime.now(_KST)
    return n.strftime("%Y-%m-%d %H") + "|" + _source_stamp()


def build_market_signal(asof: date | None = None, force: bool = False) -> dict:
    """collector 엔드포인트가 부르는 진입점. 그래프 갱신 + 파이프라인 + 정시 캐시."""
    key = _hour_key()
    if not force and asof is None and _CACHE["key"] == key and _CACHE["payload"]:
        out = dict(_CACHE["payload"])
        out["cached"] = True          # 화면이 '언제 계산된 것'인지 알 수 있게
        return out

    refresh_graph_if_stale()
    payload = run(asof=asof)
    payload["cached"] = False
    if asof is None:
        # ★결과가 비어도(시그널 0건) 캐시한다. 안 그러면 조용한 날에 10분마다
        #   87시장 스캔이 다시 돈다 — 가장 비싼 경우가 가장 자주 도는 셈이 된다.
        _CACHE["key"], _CACHE["payload"] = key, payload
    return payload
