"""보유 종목 뉴스 — 구글 뉴스 RSS.

키가 필요 없다. 다만 구글 피드의 이용 조건은 **"개인 피드리더에서 개인적·
비상업적 용도"** 다(응답의 copyright 필드). 이 대시보드는 사용자 본인의
비공개 화면이라 그 용도에 맞는다 — 상업적으로 재배포하지 말 것.

★검색어를 **영문 법인명**으로 만든다. 티커로 검색하면 짧은 티커가 다른 것을
  긁어 온다. 실측(2026-09-22, 10종목 각 100건에서 제목 언급 비율):
      영문 법인명  평균 97.3%  (최저 87% GOOGL)
      티커         평균 96.1%  (최저 91% NVDA)
      한국어       평균 82.8%  (최저 32% HUT — 41건뿐)
  한국어는 소형주에서 무너진다. 법인명은 SEC company_tickers 의 title 을 쓴다.

⚠️**ETF 는 넣지 않는다.** 실측에서 제목 언급 비율이 EETH 15% · TSL 33% ·
  GLD 43% · SOXL 58% 였다. TSL 검색은 아예 다른 회사 기사("TSL Inflection")를
  물어 왔다. ETF 의 관련 뉴스는 기초자산 뉴스인데, 그걸 그 ETF 뉴스라고 붙이면
  우리가 만들어 낸 편집 판단이 된다.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

RSS = "https://news.google.com/rss/search"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass(frozen=True)
class Article:
    ticker: str
    company: str | None
    title: str
    publisher: str | None
    published_at: datetime | None
    url: str


@dataclass(frozen=True)
class TickerNews:
    """한 종목의 조회 결과.

    ⚠️`ok=False`(못 받았다)와 `articles=[]`(받았는데 없다)는 **다른 상태**다.
    """

    ticker: str
    company: str | None
    query: str | None
    ok: bool
    reason: str | None
    articles: list[Article] = field(default_factory=list)
    #: 관련성 필터로 걸러낸 건수. 얼마나 걸렀는지 숨기지 않는다.
    filtered_out: int = 0


def _tag(name: str, blob: str) -> str | None:
    match = re.search(rf"<{name}[^>]*>(.*?)</{name}>", blob, re.S)
    if not match:
        return None
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", match.group(1))
    return html.unescape(text).strip() or None


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


# 등기명에만 붙는 법인 형태. 기사 제목에는 거의 안 나온다.
_LEGAL_FORMS = {
    "corp", "corporation", "inc", "incorporated", "co", "company", "ltd",
    "limited", "plc", "llc", "lp", "holding", "holdings", "group", "trust",
    "nv", "n.v", "sa", "s.a", "ag", "a/s", "adr", "the",
}


def search_name(title: str) -> str:
    """SEC 등기명 → 검색에 쓸 이름.

    ⚠️등기명을 그대로 따옴표로 묶으면 안 된다. 실측: `"CORNING INC /NY" stock`
      은 14건인데 `"CORNING" stock` 은 100건이다. `/NY` 같은 등록 표기와
      법인 형태는 기사 제목에 나오지 않는다.

    ⚠️뒤에서부터 반복해서 벗긴다 — "Nebius Group N.V." 는 한 번만 벗기면
      "Nebius Group N.V" 로 남아 33건밖에 안 나온다(실측).
    """
    name = re.split(r"[,/]", title)[0]
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    while len(tokens) > 1 and tokens[-1].strip(".").lower() in _LEGAL_FORMS:
        tokens.pop()
    return " ".join(tokens).strip(" .,-") or title


def title_key(title: str) -> str:
    """중복 판정용 제목 키.

    ⚠️매체가 제목 뒤에 꼬리표를 붙여 같은 기사가 다른 제목으로 온다(실측:
      "Alphabet: An Undervalued Stock…" 과 "… | Morningstar Nordics"). 구분자
      뒤를 잘라내지 않으면 같은 기사가 두 번 보인다.
    """
    head = re.split(r"\s+[|\-–—]\s+", title)[0]
    return re.sub(r"\W+", "", head.lower())


def _relevant(title: str, ticker: str, company: str | None) -> bool:
    """제목이 **이 종목을 실제로 말하고 있나.**

    ⚠️티커를 부분 문자열로 찾으면 안 된다 — "BE" 가 "BEST"·"BEFORE" 에 걸린다.
      단어 경계로 찾는다. 법인명은 첫 낱말(예: "NVIDIA CORP" → "NVIDIA")로 본다.
    """
    lowered = title.lower()
    if re.search(rf"\b{re.escape(ticker.lower())}\b", lowered):
        return True
    if company:
        head = re.split(r"[\s,]", company.strip())[0]
        if len(head) >= 3 and head.lower() in lowered:
            return True
    return False


def _fetch_one(
    client: httpx.Client, ticker: str, company: str | None, limit: int, since: datetime
) -> TickerNews:
    # 법인명이 있으면 그걸로, 없으면 티커로. 따옴표로 묶어 구를 그대로 찾게 한다.
    name = search_name(company) if company else None
    query = f'"{name}" stock' if name else f"{ticker} stock"
    try:
        response = client.get(
            RSS,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        )
        if response.status_code != 200:
            return TickerNews(
                ticker=ticker, company=company, query=query, ok=False,
                reason=f"구글 뉴스 응답 {response.status_code}",
            )
        body = response.text
    except Exception as exc:
        return TickerNews(
            ticker=ticker, company=company, query=query, ok=False,
            reason=f"조회 실패 ({type(exc).__name__})",
        )

    articles: list[Article] = []
    filtered = 0
    seen: set[str] = set()

    for blob in re.findall(r"<item>(.*?)</item>", body, re.S):
        title = _tag("title", blob)
        link = _tag("link", blob)
        if not title or not link:
            continue
        # 제목 끝의 " - 매체명" 은 RSS 가 붙인 것이다. 본문과 매체를 나눈다.
        publisher = _tag("source", blob)
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()

        when = _when(_tag("pubDate", blob))
        if when is not None and when < since:
            continue
        if not _relevant(title, ticker, name or company):
            filtered += 1
            continue
        key = title_key(title)
        if key in seen:
            continue
        seen.add(key)

        articles.append(
            Article(
                ticker=ticker, company=company, title=title,
                publisher=publisher, published_at=when, url=link,
            )
        )
        if len(articles) >= limit:
            break

    return TickerNews(
        ticker=ticker, company=company, query=query, ok=True, reason=None,
        articles=articles, filtered_out=filtered,
    )


def fetch_news(
    targets: list[tuple[str, str | None]],
    *,
    days: int = 7,
    limit_per_ticker: int = 10,
    timeout: float = 20.0,
    max_workers: int = 5,
) -> list[TickerNews]:
    """`(티커, 영문 법인명)` 목록에 대한 최근 뉴스.

    법인명이 None 이면 티커로 검색하되, 정확도가 떨어진다는 점을 호출부가 안다.
    """
    wanted = [(t.upper(), c) for t, c in targets if t]
    if not wanted:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    with httpx.Client(timeout=timeout, headers={"User-Agent": _UA}) as client:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(wanted))) as pool:
            return list(
                pool.map(
                    lambda a: _fetch_one(client, a[0], a[1], limit_per_ticker, since),
                    wanted,
                )
            )
