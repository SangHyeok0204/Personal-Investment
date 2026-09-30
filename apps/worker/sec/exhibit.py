"""실적 8-K / 6-K 의 보도자료(Ex.99.1) 찾기 · 본문 글 (계획 B2 · B4) — 원본 `sec_edgar.py` 이식.

원본 규칙 그대로:
  - 공시 고르기: 8-K Item 2.02(실적) 발표일 창 안 > Item 2.02 아무거나 > 8-K 창 안 > 6-K 창 안(외국 발행사 — NBIS 등).
    창 = 발표일 −1 ~ +7일. 6-K 는 창 밖이면 쓰지 않는다(묵은 6-K 방지).
  - 첨부 고르기: ★사람용 `{acc}-index.htm` 의 **문서 타입(EX-99.1)** 이 1순위 — `index.json` 은 공시에 따라 문서를
    아예 안 나열한다(원본 실측: CRM · NVDA · INTU · CRWD). 없으면 파일명 규칙 → 크기(표지의 2배 · 5만 바이트 이상).
  - 표지(8-K cover)만 잡히면 실적자료 없음으로 본다 — 표지에는 숫자가 없다.
바꾼 것: requests + BeautifulSoup → 공용 `sec_get`(속도 제한 · 403 멈춤) + 표준 `html.parser`(의존성 추가 없이).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from html.parser import HTMLParser

from sec.client import sec_get
from sec.ownership import cik10

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
_COVER = re.compile(r"SECURITIES\s+AND\s+EXCHANGE\s+COMMISSION", re.I)
MIN_CHARS = 500


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html or "")
    return re.sub(r"\s+", " ", " ".join(p.parts)).strip()


class _IndexTable(HTMLParser):
    """`{acc}-index.htm` 의 `tableFile` 표 → [{type, name}]."""

    def __init__(self):
        super().__init__()
        self.docs: list[dict] = []
        self._in_table = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._link_text: list[str] | None = None
        self._cell_link: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and "tableFile" in (a.get("class") or ""):
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._row is not None and tag == "td":
            self._cell, self._cell_link = [], None
        elif self._cell is not None and tag == "a":
            self._link_text = []

    def handle_endtag(self, tag):
        if tag == "table" and self._in_table:
            self._in_table = False
        elif tag == "a" and self._link_text is not None:
            self._cell_link = "".join(self._link_text).strip()
            self._link_text = None
        elif tag == "td" and self._cell is not None and self._row is not None:
            # iXBRL 행은 </a> 뒤에 배지가 붙는다 — 링크 글자만 파일명으로 쓴다(원본 주석)
            self._row.append(self._cell_link or "".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) >= 4 and self._row[2]:
                self.docs.append({"type": self._row[3], "name": self._row[2]})
            self._row = None

    def handle_data(self, data):
        if self._link_text is not None:
            self._link_text.append(data)
        if self._cell is not None:
            self._cell.append(data)


def parse_index_documents(html: str) -> list[dict]:
    p = _IndexTable()
    p.feed(html or "")
    return p.docs


def select_exhibit_by_type(docs: list[dict]) -> str | None:
    html_docs = [d for d in docs if str(d.get("name", "")).lower().endswith((".htm", ".html"))]
    for exact in (True, False):
        for d in html_docs:
            kind = str(d.get("type", "")).strip().lower().replace(" ", "")
            if (kind == "ex-99.1") if exact else kind.startswith("ex-99"):
                return d["name"]
    return None


# 원본은 두 번째 규칙이 (earnings|release|results|q[1-4]) 하나였다 — 실측 NVDA 는 'q2fy27cfocommentary.htm'(EX-99.2)이
# 목록에서 먼저 나와 보도자료 'q2fy27pr.htm' 대신 잡혔다 → 보도자료다운 이름을 분기 표기보다 먼저 본다.
_NAME_PATTERNS = (re.compile(r"(?:ex|exhibit)[-_]?(?:99|991|99\.1)", re.I),
                  re.compile(r"(?:earnings|release|results|pr\.html?$)", re.I),
                  re.compile(r"q[1-4]", re.I))


def select_release_by_name(items: list[dict], primary_document: str | None) -> str | None:
    """문서 타입으로 못 고를 때(원본 `_select_earnings_release_document`) — `index.json` 항목 [{name, size}] 에서
    파일명 규칙(ex99 → earnings/release/results/qN) → 크기(표지의 2배 · 5만 바이트 이상) 순. 다 안 되면 표지(primary).
    표지는 부르는 쪽이 `_COVER` 로 거른다.
    """
    html_items = [i for i in items if str(i.get("name", "")).lower().endswith((".htm", ".html"))]
    for pat in _NAME_PATTERNS:
        for i in html_items:
            if pat.search(i["name"]):
                return i["name"]

    def size(i):
        try:
            return int(i.get("size") or 0)
        except (TypeError, ValueError):
            return 0
    # 파일명이 규칙에 안 맞는 발행인(원본 실측 CLS 'cls-YYYYMMDDprcondensedfs.htm') — 본문은 표지보다 훨씬 크다
    cands = [i for i in html_items if not re.match(r"R\d+\.htm", i["name"], re.I) and "index" not in i["name"].lower()]
    if cands:
        largest = max(cands, key=size)
        primary_size = next((size(i) for i in cands if i["name"] == primary_document), 0)
        if size(largest) >= max(primary_size * 2, 50000):
            return largest["name"]
    return primary_document


def earnings_filing_candidates(recent: dict, asof: date | None = None) -> list[dict]:
    """submissions 의 recent 묶음 → 실적 공시 후보(우선순위 순).

    원본 `_find_recent_filing` 순서: 8-K Item 2.02 창 안 > 2.02 아무거나 > 8-K 창 안 > 6-K 창 안.
    ★바꾼 것: 6-K 는 **발표일에 가까운 순**으로 여러 개를 준다 — 원본은 창 안 첫 6-K(=가장 늦은 것)를 골라,
      실측 NBIS 2026-08-12 발표에 8/19 전환사채 공시(6-K)가 잡혔다. 부르는 쪽이 본문으로 실적 자료인지 확인한다.
    """
    forms = recent.get("form") or []
    floor = ceil = None
    if asof:
        floor, ceil = (asof - timedelta(days=1)).isoformat(), (asof + timedelta(days=7)).isoformat()
    in202, any202, eightk, sixk = [], [], [], []
    for i, form in enumerate(forms):
        if form not in ("8-K", "6-K"):
            continue
        fd = (recent.get("filingDate") or [""] * len(forms))[i]
        in_window = bool(floor and floor <= fd <= ceil)
        item = {"accession": recent["accessionNumber"][i], "primary_document": recent["primaryDocument"][i],
                "filing_date": fd, "form": form}
        if form == "8-K":
            has202 = "2.02" in str((recent.get("items") or [""] * len(forms))[i])
            if has202:
                (in202 if in_window else any202).append(item)
            elif in_window:
                eightk.append(item)
        elif in_window:
            sixk.append(item)
    if asof:
        sixk.sort(key=lambda x: abs(date.fromisoformat(x["filing_date"]) - asof))
        # ★발표일이 있으면 '창 밖의 아무 2.02'는 쓰지 않는다 — 원본 순서(2.02 아무거나 > 창 안 8-K)는 지난 발표에
        #   **가장 최근 분기** 8-K 를 붙였다(실측 GLW 2026-04-28: 그날 8-K 에 Item 2.02 표시가 없어 7/28 2분기 것이 잡힘).
        return in202 + eightk + sixk
    return in202 + any202[:1] + eightk + sixk


def pick_earnings_filing(recent: dict, asof: date | None = None) -> dict | None:
    c = earnings_filing_candidates(recent, asof)
    return c[0] if c else None


_RESULTS_WORDS = re.compile(r"(quarter|results|fiscal|three months)", re.I)


def looks_like_results(text: str) -> bool:
    """실적 보도자료다운가 — 매출 언급 + 분기/실적 표현(전환사채 · 인사 공시 같은 다른 6-K 를 거른다)."""
    head = text[:6000]
    # 'revenue' 만 보면 안 된다 — Corning 은 'core sales' 라고 쓴다(실측 GLW 2026-04-28 실적 보도자료가 떨어짐)
    return bool(re.search(r"revenue|sales", head, re.I)) and bool(_RESULTS_WORDS.search(head))


def earnings_release(client, cik: str, asof: date | None = None, max_chars: int = 15000) -> dict | None:
    """→ {accession, form, filing_date, url, text} 또는 None(공시 없음 · 첨부 못 찾음 · 표지뿐)."""
    cik = cik10(cik)
    r = sec_get(client, SUBMISSIONS.format(cik=cik))
    if r.status_code != 200:
        return None
    for filing in earnings_filing_candidates(r.json()["filings"]["recent"], asof)[:6]:
        acc, nodash = filing["accession"], filing["accession"].replace("-", "")
        idx = sec_get(client, ARCHIVE.format(cik=int(cik), acc=nodash, doc=f"{acc}-index.htm"))
        doc = select_exhibit_by_type(parse_index_documents(idx.text)) if idx.status_code == 200 else None
        if not doc:                                  # 타입이 없으면 파일명 → 크기 (원본 폴백)
            js = sec_get(client, ARCHIVE.format(cik=int(cik), acc=nodash, doc="index.json"))
            items = (js.json().get("directory") or {}).get("item") or [] if js.status_code == 200 else []
            doc = select_release_by_name(items, filing.get("primary_document"))
        if not doc:
            continue
        url = ARCHIVE.format(cik=int(cik), acc=nodash, doc=doc)
        resp = sec_get(client, url)
        if resp.status_code != 200:
            continue
        text = html_to_text(resp.text)
        if len(text) < MIN_CHARS or _COVER.search(text[:600]) or not looks_like_results(text):
            continue
        return {**filing, "url": url, "text": text[:max_chars].rsplit(" ", 1)[0]}
    return None
