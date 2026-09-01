# -*- coding: utf-8 -*-
r"""[시장 시그널] 2단 — 온톨로지 탐색으로 가설 도출 (2026-08-31 신설).

1단(signal_rules)이 "튀었다"만 말한다. 이 단은 **"튄 게 시장의 반응과 연결돼 있나"**
를 묻는다. 시그널 노드에서 출발해 knowledge.ttl(인과 구조) + markets.ttl(당일 관측)
두 그래프를 함께 걸어 가설을 세운다.

━━ 왜 SPARQL 을 안 쓰나 ━━
질의가 "이 노드의 이웃" 수준이라 트리플 순회로 충분하다. rdflib 의 SPARQL 은 파싱·
플랜 비용이 질의당 수십 ms 라, 시그널 8건 × 가설 6종이면 그게 전부 요청 지연이 된다.
`graph.objects(s, p)` 직접 호출이 같은 답을 마이크로초에 준다.

━━ 가설 6종 (우선순위 = knowledge.ttl 의 mk:priority) ━━
  5 InversionBreak — 평소 반대로 가던 둘이 같은 방향. 정보량이 가장 크다.
  4 Divergence     — 같은 묶음인데 부호가 갈렸다.
  4 DriverLed      — 그 시장의 동인 프록시가 같이 움직였다.
  3 BroadMove      — 묶음 과반이 같이 움직였다. **여러 시그널을 1건으로 접는다.**
  3 Transmission   — 상류 시장이 먼저 움직였다.
  2 Idiosyncratic  — 아무것도 안 걸렸다 = 그 시장 고유 재료. **뉴스 검색 가치 최고.**

★★접기(collapse)가 이 단의 존재 이유 중 하나다. 2026-08-31 실측에서 1단이 크립토
  5종(BTC·ETH·SOL·크립토지수·비트코인ETF)을 따로 뱉었는데, 그건 5건이 아니라
  "암호화폐 전반 강세" 1건이다. 카드가 1건만 보여주므로 접지 않으면 같은 사건이
  화면을 독식한다.
"""
from __future__ import annotations

import os
from collections import defaultdict

MK = "http://ge.local/market#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

_HERE = os.path.dirname(os.path.abspath(__file__))

# knowledge.ttl 은 **손으로 쓴 소스**다 → 패키지 안에 산다(이미지에 구워지는 게 맞다).
KNOWLEDGE_TTL = os.environ.get("MS_KNOWLEDGE_TTL", os.path.join(_HERE, "knowledge.ttl"))


def _default_markets_ttl() -> str:
    """markets.ttl 은 **매일 굽는 생성물**이다 → 캐시 볼륨에 둔다.

    ★★2026-08-31 8회차에 고쳤다. 그 전에는 패키지 디렉터리(`_HERE`)에 썼는데 셋 다 나빴다:
      ① 생성물이 **git 에 커밋**된다(gitignore 안 돼 있었다)
      ② 빌드 시점의 낡은 ttl 이 **이미지에 구워져** 배포된다 — 내 개발 PC에서 만든
         어제 데이터가 마치 현재 것처럼 실린다
      ③ 컨테이너를 다시 만들면 그날 구운 게 날아가고 구운 이미지 것으로 되돌아간다
    `/app/.cache` 는 이 저장소가 생성물에 쓰는 named volume 이다(legacy_inputs.CACHE_DIR,
    index_window 의 DB 사본도 같은 자리) — 재기동에도 살아남는다.
    ★캐시 디렉터리가 없으면(로컬 개발·테스트) 패키지 옆으로 떨어뜨린다.
    """
    cache = os.environ.get("COLLECTOR_CACHE_DIR", "/app/.cache")
    try:
        d = os.path.join(cache, "market_signal")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "markets.ttl")
    except OSError:
        return os.path.join(_HERE, "markets.ttl")


MARKETS_TTL = os.environ.get("MS_MARKETS_TTL") or _default_markets_ttl()

# 이웃이 "같이 움직였다"고 부를 최소 크기 — 시그널 크기의 이 비율 이상.
# ★절대값 임계를 쓰면 안 된다(1단과 같은 이유). 시그널 자신의 크기에 비례시킨다.
COMOVE_FRAC = 0.35
BROAD_MIN = 2          # 묶음에서 이만큼 걸려야 '전반'으로 접는다
CORR_STRONG = 0.70     # 이만큼 붙어 있어야 "같이 움직였나"를 물을 값어치가 있다
CORR_PEERS = 6         # 한 시장당 확인할 상관 이웃 수(|r| 큰 순)


def _load():
    """두 ttl 을 한 그래프로. mtime 캐시 — markets.ttl 은 매일 바뀐다."""
    import rdflib
    g = rdflib.Graph()
    for p in (KNOWLEDGE_TTL, MARKETS_TTL):
        if os.path.exists(p):
            with open(p, "rb") as f:          # ★경로를 넘기면 rdflib 가 URL 로 오해한다
                g.parse(source=f, format="turtle")
    return g


_CACHE: dict = {"sig": None, "g": None}


def load_graph(force: bool = False):
    sig = tuple(
        (os.path.getmtime(p), os.path.getsize(p)) if os.path.exists(p) else None
        for p in (KNOWLEDGE_TTL, MARKETS_TTL)
    )
    if not force and _CACHE["sig"] == sig and _CACHE["g"] is not None:
        return _CACHE["g"]
    g = _load()
    _CACHE["sig"], _CACHE["g"] = sig, g
    return g


class Graph:
    """탐색에 필요한 인접 정보를 티커 키로 펼쳐 둔 뷰.

    ★rdflib 그래프를 매 질의마다 훑지 않고, 기동 때 한 번 dict 로 편다 —
      시그널 8건이 각각 이웃을 여러 번 묻는데 그때마다 트리플을 훑을 이유가 없다.
    """

    def __init__(self, g=None):
        import rdflib
        self.g = g if g is not None else load_graph()
        self._rdflib = rdflib
        U = rdflib.URIRef

        self.by_ticker: dict[str, str] = {}     # ticker -> uri
        self.label: dict[str, str] = {}         # uri -> 표시명
        self.ret: dict[str, dict] = defaultdict(dict)   # uri -> {dtd,wtd,mtd,...}
        self.regime: dict[str, str] = {}
        self.asset: dict[str, str] = {}

        for s, _p, o in self.g.triples((None, U(MK + "ticker"), None)):
            self.by_ticker[str(o)] = str(s)
        for s, _p, o in self.g.triples((None, U(RDFS_LABEL), None)):
            self.label[str(s)] = str(o)
        for key, prop in (("dtd", "retDtd"), ("wtd", "retWtd"), ("mtd", "retMtd"),
                          ("r1m", "ret1m"), ("r3m", "ret3m")):
            for s, _p, o in self.g.triples((None, U(MK + prop), None)):
                self.ret[str(s)][key] = float(o)
        for s, _p, o in self.g.triples((None, U(MK + "hasRegime"), None)):
            self.regime[str(s)] = str(o).split("#")[-1]
        for s, _p, o in self.g.triples((None, U(MK + "inAssetClass"), None)):
            self.asset[str(s)] = str(o).split("#")[-1]
        # 티커 → is_yield. 이웃의 부호를 가격 기준으로 뒤집을 때 쓴다.
        self.is_yield: dict[str, bool] = {}
        for s, _p, o in self.g.triples((None, U(MK + "isYield"), None)):
            t = self._ticker_of(s)
            if t:
                self.is_yield[t] = bool(o.toPython())

        # knowledge.ttl 쪽 — 묶음·동인·전이·역상관
        self.groups: dict[str, list[str]] = defaultdict(list)   # group uri -> [mkt uri]
        self.member_of: dict[str, list[str]] = defaultdict(list)
        for s, _p, o in self.g.triples((None, U(MK + "memberOf"), None)):
            t = self._ticker_of(s)
            if t:
                self.groups[str(o)].append(t)
                self.member_of[t].append(str(o))
        self.driven_by: dict[str, list[str]] = defaultdict(list)
        for s, _p, o in self.g.triples((None, U(MK + "drivenBy"), None)):
            t = self._ticker_of(s)
            if t:
                self.driven_by[t].append(str(o).split("#")[-1])
        self.proxy_of: dict[str, str] = {}      # driver -> ticker
        for s, _p, o in self.g.triples((None, U(MK + "proxyFor"), None)):
            t = self._ticker_of(s)
            if t:
                self.proxy_of[str(o).split("#")[-1]] = t
        self.transmits: dict[str, list[str]] = defaultdict(list)   # src t -> [dst t]
        self.upstream: dict[str, list[str]] = defaultdict(list)    # dst t -> [src t]
        for s, _p, o in self.g.triples((None, U(MK + "transmitsTo"), None)):
            a, b = self._ticker_of(s), self._ticker_of(o)
            if a and b:
                self.transmits[a].append(b)
                self.upstream[b].append(a)
        self.inverted: dict[str, list[str]] = defaultdict(list)
        for s, _p, o in self.g.triples((None, U(MK + "invertedWith"), None)):
            a, b = self._ticker_of(s), self._ticker_of(o)
            if a and b:
                self.inverted[a].append(b)
                self.inverted[b].append(a)

        # 실측 상관 간선(markets.ttl, 최근 1년) — 양방향으로 편다.
        # ★★2026-08-31 4회차에 **빠져 있던 것**을 채웠다. build_graph 가 225간선을
        #   굽는데 탐색이 한 번도 안 읽어 전부 죽은 데이터였다. 사용자가 KG 내용으로
        #   명시한 항목("a와 b는 최근 1년 상관 0.xx")이라 반드시 써야 한다.
        self.corr: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for s in self.g.subjects(U(RDF_TYPE), U(MK + "Correlation")):
            a = self._ticker_of(self.g.value(s, U(MK + "subjectMarket")))
            b = self._ticker_of(self.g.value(s, U(MK + "objectMarket")))
            v = self.g.value(s, U(MK + "corrValue"))
            if a and b and v is not None:
                r = float(v)
                self.corr[a].append((b, r))
                self.corr[b].append((a, r))
        for k in self.corr:
            self.corr[k].sort(key=lambda x: -abs(x[1]))

        # 매크로 동조(markets.ttl, 최근 1개월)
        self.comove: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for s in self.g.subjects(U(RDF_TYPE), U(MK + "MacroComove")):
            m = self.g.value(s, U(MK + "subjectMarket"))
            d = self.g.value(s, U(MK + "driver"))
            v = self.g.value(s, U(MK + "corrValue"))
            t = self._ticker_of(m)
            if t and d is not None and v is not None:
                self.comove[t].append((str(d).split("#")[-1], float(v)))

        self.group_label = {u: self.label.get(u, u.split("#")[-1])
                            for u in self.groups}
        self.driver_label: dict[str, str] = {}
        for s, _p, o in self.g.triples((None, U(RDFS_LABEL), None)):
            if str(s).startswith(MK):
                self.driver_label[str(s).split("#")[-1]] = str(o)

    def _ticker_of(self, uri) -> str | None:
        """URI → 티커. knowledge.ttl 은 mk:SPX, markets.ttl 은 mk:M_SPX_Index 라
        둘 다 mk:ticker 를 갖고 있어야 접합된다."""
        import rdflib
        v = self.g.value(rdflib.URIRef(str(uri)), rdflib.URIRef(MK + "ticker"))
        return str(v) if v is not None else None

    def uri(self, ticker: str) -> str | None:
        return self.by_ticker.get(ticker)

    def ret_of(self, ticker: str, horizon: str) -> float | None:
        """티커+기간 → 그 시장의 당일 수익률. markets.ttl 노드에서 읽는다."""
        for u, _t in ((self.by_ticker.get(ticker), None),):
            pass
        # markets.ttl 인스턴스(M_*)의 값을 쓴다 — knowledge.ttl 노드에는 수익률이 없다.
        import rdflib
        U = rdflib.URIRef
        for s in self.g.subjects(U(MK + "ticker"), rdflib.Literal(ticker)):
            d = self.ret.get(str(s))
            if d and horizon in d:
                return d[horizon]
        return None

    def label_of(self, ticker: str) -> str:
        import rdflib
        U = rdflib.URIRef
        for s in self.g.subjects(U(MK + "ticker"), rdflib.Literal(ticker)):
            if str(s) in self.label and str(s).split("#")[-1].startswith("M_"):
                return self.label[str(s)]
        return ticker


DIR_WORD = {1: "강세", -1: "약세"}
# ★★채권은 **금리 언어**로 쓴다(2026-09-01). 차트가 절대 금리 수준을 그리는데 문장만
#   가격 기준("약세")이면 읽는 사람이 매번 뒤집어 생각해야 한다.
#   price_dir 는 이미 가격 기준으로 뒤집혀 있으므로: 가격 −1 = 금리 상승.
DIR_WORD_YIELD = {1: "금리 하락", -1: "금리 상승"}


def dir_word(d: int, is_yield: bool) -> str:
    return (DIR_WORD_YIELD if is_yield else DIR_WORD).get(d, "변동")


def price_dir(sig: dict) -> int:
    """시그널의 방향을 **가격 기준**으로 돌려준다.

    ★★금리는 오르면 채권 **약세**다. 시트가 주는 값이 yield 라 direction 을 그대로
      '강세'로 옮기면 정반대 문장이 나간다 — 2026-08-31 첫 실행에서 실제로
      "2Y 단독 강세"(금리 +23bp = 채권 약세인데)가 나왔다.
    """
    d = sig.get("direction") or 0
    return -d if sig.get("is_yield") else d


# 룰별 비교 지평. ★★60일 이평 크로스를 이웃의 **당일** 수익률과 비교하면 안 된다 —
#   사과와 오렌지다. 크로스·연속·돌파는 수 주에 걸친 현상이라 이웃도 월간으로 봐야 한다.
#   (2026-08-31 4회차: 국고채 5Y 크로스를 3Y 의 당일 +5.30bp 와 비교하고 있었다.)
RULE_HORIZON = {
    "spike": None,          # 시그널 자신의 metric(dtd/wtd/mtd)을 쓴다
    "trend_flip": "mtd",
    "streak": "wtd",
    "range_break": "mtd",
    "vol_regime": "mtd",
}


def horizon_of(sig: dict) -> str:
    """이웃을 어느 기간으로 볼 것인가."""
    h = RULE_HORIZON.get(sig.get("rule"), "dtd")
    if h is None:
        m = sig.get("metric")
        return m if m in ("dtd", "wtd", "mtd") else "dtd"
    return h


def _same_dir(a: float | None, b: int, is_yield_a: bool = False) -> bool:
    """이웃 값 a 가 방향 b 와 같은 쪽인가(가격 기준)."""
    if a is None or not b:
        return False
    da = (1 if a > 0 else -1)
    if is_yield_a:
        da = -da
    return da == b


def interpret(signals: list[dict], G: "Graph | None" = None) -> list[dict]:
    """1단 시그널 목록 → 가설 목록(우선순위·신뢰도 내림차순).

    반환 원소::
        {"hypothesis": "BroadMove", "priority": 3, "asset_class": "crypto",
         "headline": "암호화폐", "summary": "암호화폐 전반 강세",
         "signals": [...], "evidence": [...], "confidence": 0.0~1.0}
    """
    if G is None:
        G = Graph()
    out: list[dict] = []
    used: set[str] = set()

    # ── ① 묶음 접기 — 같은 PeerGroup 에서 같은 방향으로 2건 이상이면 1건으로 ──
    by_group: dict[str, list[dict]] = defaultdict(list)
    for s in signals:
        for grp in G.member_of.get(s["market"], []):
            by_group[grp].append(s)
    for grp, ss in sorted(by_group.items(), key=lambda kv: -len(kv[1])):
        fresh = [s for s in ss if s["market"] not in used]
        if len(fresh) < BROAD_MIN:
            continue
        dirs = [price_dir(s) for s in fresh if price_dir(s)]
        if not dirs or len(set(dirs)) != 1:
            continue                      # 부호가 갈리면 전반이 아니라 역행이다(아래 ②)
        d = dirs[0]
        glabel = G.group_label.get(grp, grp.split("#")[-1])
        for s in fresh:
            used.add(s["market"])
        yld = any(x.get("is_yield") for x in fresh)
        out.append(_hyp(
            "BroadMove", 3, fresh,
            headline=glabel,
            summary=f"{glabel} 전반 {dir_word(d, yld)}",
            evidence=[f"{s['label']} {s['note']}" for s in fresh[:4]],
            confidence=min(1.0, 0.45 + 0.12 * len(fresh)),
        ))

    # ── ②~⑤ 남은 시그널을 하나씩 ──
    for s in signals:
        if s["market"] in used:
            continue
        t, d = s["market"], price_dir(s)          # ★가격 기준 방향
        yld = bool(s.get("is_yield"))             # ★채권이면 문장을 금리 언어로
        hz = horizon_of(s)                        # ★이웃을 볼 기간(룰 성격에 맞춤)
        hyps: list[dict] = []

        # ② 역상관 붕괴 — 평소 반대인 짝이 같은 방향으로 갔다
        for other in G.inverted.get(t, []):
            ov = G.ret_of(other, hz)
            if ov is None or not d:
                continue
            if (ov > 0) == (d > 0) and abs(ov) >= abs(s["value"] or 0) * COMOVE_FRAC:
                hyps.append(_hyp(
                    "InversionBreak", 5, [s],
                    headline=s["label"],
                    summary=f"{s['label']}·{G.label_of(other)} 동반 {dir_word(d, yld)}",
                    evidence=[f"평소 역상관인 {G.label_of(other)} 도 {ov:+.2f} 로 같은 방향"],
                    confidence=0.75,
                ))
                break

        # ③ 묶음 내 역행 — 같은 묶음인데 부호가 갈렸다
        for grp in G.member_of.get(t, []):
            peers = [p for p in G.groups[grp] if p != t]
            opp = [p for p in peers
                   if (pv := G.ret_of(p, hz)) is not None and d and (pv > 0) != (d > 0)
                   and abs(pv) >= abs(s["value"] or 0) * COMOVE_FRAC]
            if len(opp) >= max(2, len(peers) // 2):
                glabel = G.group_label.get(grp, grp.split("#")[-1])
                hyps.append(_hyp(
                    "Divergence", 4, [s],
                    headline=glabel,
                    summary=f"{glabel} 내 {s['label']} 역행",
                    evidence=[f"같은 묶음 {len(opp)}개가 반대 방향"],
                    confidence=0.65,
                ))
                break

        # ④ 동인 주도 — 그 시장의 동인 프록시가 같이 움직였다
        for drv in G.driven_by.get(t, []):
            proxy = G.proxy_of.get(drv)
            if not proxy or proxy == t:
                continue
            pv = G.ret_of(proxy, hz)
            if pv is None or not d:
                continue
            comov = dict(G.comove.get(t, [])).get(drv)
            if abs(pv) < abs(s["value"] or 0) * COMOVE_FRAC:
                continue
            # ★★부호를 반드시 본다. 크기만 보면 **반대로 움직인 동인**도 '주도'로
            #   잡힌다 — 첫 실행에서 SOX 가 -3.47 인데 대만 가권 골든크로스를 두고
            #   "반도체 사이클 영향 강세"라고 썼다. 동조 r 의 부호까지 함께 본다.
            expect = d if (comov is None or comov >= 0) else -d
            if not _same_dir(pv, expect, G.is_yield.get(proxy, False)):
                continue
            dl = G.driver_label.get(drv, drv)
            ev = [f"{dl} 프록시({G.label_of(proxy)}) {pv:+.2f}"]
            if comov is not None:
                ev.append(f"최근 1개월 동조 r={comov:+.2f}")
            hyps.append(_hyp(
                "DriverLed", 4, [s],
                headline=s["label"],
                summary=f"{s['label']} {dl} 영향",
                evidence=ev,
                confidence=0.6 + (0.15 if comov and abs(comov) >= 0.5 else 0),
            ))
            break

        # ⑤ 전이 — 상류 시장이 먼저 움직였다
        for src in G.upstream.get(t, []):
            sv = G.ret_of(src, hz)
            if sv is None or not d:
                continue
            if (abs(sv) >= abs(s["value"] or 0) * COMOVE_FRAC
                    and _same_dir(sv, d, G.is_yield.get(src, False))):
                hyps.append(_hyp(
                    "Transmission", 3, [s],
                    headline=s["label"],
                    summary=f"{s['label']}: {G.label_of(src)} 발 전이",
                    evidence=[f"상류 {G.label_of(src)} {sv:+.2f}"],
                    confidence=0.55,
                ))
                break

        # ⑥ 실측 상관 — 강하게 붙은 이웃이 **기대 방향으로** 같이 움직였나.
        #   ★r 의 부호가 기대 방향을 정한다: r>0 이면 같은 방향, r<0 이면 반대 방향이
        #     '정상'이다. 부호를 안 보면 역상관 짝이 반대로 간 것도 '동반'이라 부르게 된다.
        if not hyps:
            conf: list[tuple[str, float, float]] = []
            for other, r in G.corr.get(t, [])[:CORR_PEERS]:
                if abs(r) < CORR_STRONG or other == t:
                    continue
                ov = G.ret_of(other, hz)
                if ov is None or not d:
                    continue
                expect = d if r > 0 else -d
                if (_same_dir(ov, expect, G.is_yield.get(other, False))
                        and abs(ov) >= abs(s["value"] or 0) * COMOVE_FRAC):
                    conf.append((other, r, ov))
            if conf:
                names = " · ".join(G.label_of(o) for o, _r, _v in conf[:2])
                hyps.append(_hyp(
                    "Correlated", 3, [s],
                    headline=s["label"],
                    summary=f"{s['label']}·{G.label_of(conf[0][0])} 동반 {dir_word(d, yld)}",
                    evidence=[f"최근 1년 상관 {r:+.2f} 인 {G.label_of(o)} 도 {v:+.2f}"
                              for o, r, v in conf[:2]],
                    confidence=min(0.8, 0.45 + 0.12 * len(conf)),
                ))

        if hyps:
            hyps.sort(key=lambda h: (-h["priority"], -h["confidence"]))
            out.append(hyps[0])
        else:
            # ⑥ 아무것도 안 걸렸다 = 고유 재료. **뉴스 검색 가치가 가장 높다.**
            # ★근거를 구체적으로 쓴다. "아무것도 안 걸림"은 정보가 아니다 —
            #   "상관 0.9 인 X 조차 안 움직였다"가 곧 고유 재료의 증거다.
            # ★★문구를 사실대로 나눈다. 앞선 판(4회차)은 이웃이 **얼마를 움직였든**
            #   "잠잠"이라 썼다 — "상관 0.96 인 국고채 3Y 는 +5.30 으로 잠잠" 처럼
            #   대놓고 틀린 문장이 나갔다. 셋으로 가른다:
            #     · 거의 안 움직임      → "잠잠"
            #     · 기대와 반대로 움직임 → "반대로"  (상관 붕괴 — 오히려 정보다)
            #     · 같은 방향인데 약함   → "미약"
            ev = []
            for other, r in G.corr.get(t, [])[:3]:
                if abs(r) < CORR_STRONG:
                    continue
                ov = G.ret_of(other, hz)
                lb, u = G.label_of(other), ("bp" if G.is_yield.get(other) else "%")
                if ov is None:
                    ev.append(f"상관 {r:+.2f} 인 {lb} 는 관측 없음")
                    continue
                thr = abs(s["value"] or 0) * COMOVE_FRAC
                expect = d if r > 0 else -d
                if abs(ov) < thr * 0.5:
                    ev.append(f"상관 {r:+.2f} 인 {lb} 는 {ov:+.2f}{u} 로 잠잠")
                elif not _same_dir(ov, expect, G.is_yield.get(other, False)):
                    ev.append(f"상관 {r:+.2f} 인데 {lb} 는 {ov:+.2f}{u} 로 **반대**")
                else:
                    ev.append(f"상관 {r:+.2f} 인 {lb} 는 {ov:+.2f}{u} (동행은 약함)")
            out.append(_hyp(
                "Idiosyncratic", 2, [s],
                headline=s["label"],
                summary=f"{s['label']} 단독 {dir_word(d, yld)}",
                evidence=ev or ["묶음·동인·상류 어디도 같이 움직이지 않음"],
                confidence=0.5 + (0.1 if ev else 0),
            ))
        used.add(t)

    out.sort(key=lambda h: (-h["priority"], -h["confidence"],
                            -max(x["severity"] for x in h["signals"])))
    return out


def _hyp(kind, priority, signals, headline, summary, evidence, confidence) -> dict:
    return {
        "hypothesis": kind,
        "priority": priority,
        "asset_class": signals[0]["asset_class"],
        "headline": headline,
        "summary": summary,
        "evidence": evidence,
        "confidence": round(float(confidence), 2),
        "severity": round(max(s["severity"] for s in signals), 2),
        "signals": [{k: v for k, v in s.items() if k != "indicators"} for s in signals],
    }
