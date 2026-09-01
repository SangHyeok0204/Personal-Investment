# -*- coding: utf-8 -*-
r"""[시장 시그널] 3단 — 가설을 뒷받침할 뉴스가 있는가 (2026-08-31 신설).

2단이 세운 가설("암호화폐 전반 강세")을 들고 뉴스를 찾아, **근거가 합리적으로
확보될 때만** 카드에 올린다. 근거가 없으면 가설은 살아 있되 `supported=False` 로
남고, 카드는 그 다음 후보로 넘어간다.

★★**컨테이너에서 직접 돈다**(2026-08-31 실측: collector 안에서 news.google.com RSS
  HTTP 200). AI 요약만 밖으로 빼면 되고 뉴스 수집은 안에서 된다 — 첫 설계에서
  "전부 밖으로"라고 잡았던 걸 여기서 되돌린다.

★표준 라이브러리만 쓴다. 주간가격모니터 선례(`crawlers/bond_curve_news.py`)는
  aiohttp 를 쓰지만 collector 는 그 의존성이 없고, 가설 몇 개에 쿼리 몇 개면
  urllib 순차 호출로 충분하다(실측 쿼리당 0.3~0.8초).

★★**"뉴스가 있다"를 근거로 착각하면 안 된다.** 어떤 시장이든 매일 기사는 나온다.
  그래서 세 가지를 같이 본다:
    1. **최근성** — 시그널이 난 창(기본 48시간) 안의 기사만 센다.
    2. **일치도** — 제목이 그 시장/동인 어휘를 실제로 포함하는가.
    3. **방향성** — 상승/하락 어휘가 가설 방향과 맞는가(맞으면 가점, 반대면 감점).
  셋을 곱해 점수를 내고 임계를 넘어야 supported 다.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
TIMEOUT = 8
WINDOW_H = 48          # 이 시간 안의 기사만 근거로 센다
MAX_PER_QUERY = 10
SUPPORT_MIN = 2.0      # 이 점수를 넘어야 '근거 확보'

# 방향 어휘 — 가설 방향과 맞는지 본다. 한국어 기사 기준.
UP_WORDS = ("급등", "상승", "강세", "랠리", "반등", "사상 최고", "신고가", "훈풍", "호조")
DOWN_WORDS = ("급락", "하락", "약세", "폭락", "조정", "신저가", "부진", "충격", "우려")

# 동인 → 검색 어휘. knowledge.ttl 의 mk:Driver 와 1:1.
DRIVER_TERMS = {
    "USRates": ["미국 국채 금리", "Fed 금리", "FOMC"],
    "Dollar": ["달러 강세", "달러인덱스", "환율"],
    "RiskAppetite": ["위험자산", "비트코인", "투자심리"],
    "ChinaGrowth": ["중국 경기", "중국 부양책", "구리 가격"],
    "OilSupply": ["국제유가", "OPEC", "원유 재고"],
    "SemiCycle": ["반도체 업황", "메모리 가격", "AI 반도체"],
    "JapanPolicy": ["일본은행", "엔화", "BOJ"],
    "Inflation": ["물가", "인플레이션", "금값"],
}


def _get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GE-market-signal/1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except Exception:
        return None      # ★뉴스 실패가 파이프라인을 죽이면 안 된다. 근거 0으로 흘린다.


def _parse(raw: bytes) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        pub = it.findtext("pubDate") or ""
        out.append({"title": title, "pub": pub, "link": it.findtext("link") or "",
                    "at": _pubdate(pub)})
    return out[:MAX_PER_QUERY]


def _pubdate(s: str) -> datetime | None:
    """RFC822 → aware datetime. 실패하면 None(=최근성 점수 0)."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def queries_for(hyp: dict) -> list[str]:
    """가설 → 검색어 목록. 시장 이름 + 동인 어휘를 섞는다.

    ★시장 이름만으로 검색하면 그 시장의 일상 기사가 잡힌다. 동인 어휘를 같이 넣어야
      "왜 움직였나"에 닿는 기사가 나온다.
    """
    qs: list[str] = []
    head = hyp.get("headline") or ""
    if head:
        qs.append(head)
    for s in hyp.get("signals", [])[:2]:
        lb = s.get("label")
        if lb and lb not in qs:
            qs.append(lb)
    # 동인 가설이면 동인 어휘를 얹는다.
    summ = hyp.get("summary", "")
    for drv, terms in DRIVER_TERMS.items():
        if any(t.split()[0] in summ for t in terms) or drv in summ:
            qs.extend(terms[:2])
            break
    return qs[:3]        # 쿼리 3개면 충분하다 — 늘려도 같은 기사가 겹친다


def _direction_of(hyp: dict) -> int:
    if "강세" in hyp.get("summary", "") or "상승" in hyp.get("summary", ""):
        return 1
    if "약세" in hyp.get("summary", "") or "하락" in hyp.get("summary", ""):
        return -1
    ss = hyp.get("signals") or [{}]
    return ss[0].get("direction") or 0


def gather(hyp: dict, now: datetime | None = None) -> dict:
    """가설 하나에 대해 뉴스를 모으고 근거 점수를 낸다.

    반환:: {"supported": bool, "score": float, "articles": [...], "queries": [...]}
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=WINDOW_H)
    want_dir = _direction_of(hyp)
    qs = queries_for(hyp)

    seen: set[str] = set()
    arts: list[dict] = []
    for q in qs:
        raw = _get(RSS.format(q=urllib.parse.quote(q)))
        if not raw:
            continue
        for a in _parse(raw):
            key = re.sub(r"\W+", "", a["title"])[:40]
            if key in seen:
                continue
            seen.add(key)
            a["query"] = q
            arts.append(a)

    # ── 점수 ──
    score = 0.0
    kept: list[dict] = []
    terms = [t for t in ([hyp.get("headline")] +
                         [s.get("label") for s in hyp.get("signals", [])]) if t]
    for a in arts:
        if a["at"] is None or a["at"] < cutoff:
            continue                                  # ① 최근성
        title = a["title"]
        hit = any(t and t in title for t in terms)     # ② 일치도
        w = 1.0 if hit else 0.35
        up = any(k in title for k in UP_WORDS)
        dn = any(k in title for k in DOWN_WORDS)
        if want_dir and (up or dn):                   # ③ 방향성
            same = (up and want_dir > 0) or (dn and want_dir < 0)
            w *= 1.5 if same else 0.3
        score += w
        a["weight"] = round(w, 2)
        kept.append(a)

    kept.sort(key=lambda x: -x["weight"])
    return {
        "supported": score >= SUPPORT_MIN,
        "score": round(score, 2),
        "queries": qs,
        "articles": [{"title": a["title"], "link": a["link"], "pub": a["pub"],
                      "weight": a["weight"]} for a in kept[:5]],
        "n_total": len(arts),
        "n_recent": len(kept),
    }
