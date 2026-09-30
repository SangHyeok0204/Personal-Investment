"""EDGAR 회사 검색 — 13F-HR 을 낸 운용사만 (계획 A7 거장 추가).

원본 `13F기관내부자/src/resolver.py` 의 `InvestorResolver` 를 옮겼다. `browse-edgar?type=13F-HR` 는
- 한 곳만 맞으면 그 회사의 공시 목록 페이지(`class="companyName"` + `CIK=NNNNNNNNNN`),
- 여러 곳이면 회사 목록 표(CIK 링크 + 회사명 칸)를 돌려준다.
⚠️**운용사 이름**으로 찾는다 — 사람 이름(예: einhorn)은 0건이다(실측). 화면이 그렇게 안내한다.
검색 한 번 = SEC 요청 1회. UA 는 worker 와 같은 `SEC_USER_AGENT`(없으면 검색하지 않는다).
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

import httpx

SEARCH_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={q}"
              "&type=13F-HR&dateb=&owner=include&count=40")


def pad_cik(v) -> str:
    return re.sub(r"\D", "", str(v)).zfill(10)


def parse_search(page: str) -> list[dict]:
    """검색 결과 HTML → [{cik, name}]."""
    m = re.search(r'class="companyName">([^<]+?)\s*<', page)
    if m:
        cm = re.search(r"CIK=(\d{10})", page)
        return [{"cik": cm.group(1), "name": html.unescape(m.group(1)).strip()}] if cm else []
    out, seen = [], set()
    for cik, _, name in re.findall(r'CIK=(\d+)[^>]*>([^<]*)</a>\s*</td>\s*<td[^>]*>([^<]*)</td>', page):
        cik = pad_cik(cik)
        name = html.unescape(name).strip()
        if name and cik not in seen:
            seen.add(cik)
            out.append({"cik": cik, "name": name})
    return out


def search_13f_filers(query: str, user_agent: str, client: httpx.Client | None = None) -> list[dict]:
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(SEARCH_URL.format(q=quote_plus(query.strip())), headers={"User-Agent": user_agent})
        resp.raise_for_status()
        return parse_search(resp.text)
    finally:
        if own:
            client.close()
