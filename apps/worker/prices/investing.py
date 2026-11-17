"""Investing.com 실적 캘린더 — 매출 컨센(과 지난 날짜의 매출 실적) (계획 B3b · 사용자 결정 5 = 2안).

원본 `earnings_crawler.py` 이식. Nasdaq · Yahoo 는 무료로 매출 컨센을 주지 않는다(실측) — 이게 크롤을 두는 이유다.

⚠️**화면 있는 크롬**이어야 한다: 2026-07-17 부터 Cloudflare 가 헤드리스 Chromium 을 "Just a moment..." 에서 막는다
  (원본 주석). `channel="chrome"`(설치된 크롬) · `headless=False` · 창은 화면 밖(-32000,-32000). → 이 맥의
  **로그인된 GUI 세션**(LaunchAgent gui 도메인)에서만 돈다. 도커 불가.
⚠️커스텀 UA 를 주지 않는다 — 실제 크롬 버전과 어긋나면 그 자체가 봇 신호다(원본 주석).
바꾼 것: 기간 전체가 아니라 **내 종목이 발표하는 날짜만** 돈다(하루 한두 쪽). Cloudflare 에 걸리면 `InvestingBlocked`.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date

URL = "https://www.investing.com/earnings-calendar/"
_TABLE = "table[class*='datatable-v2_table']"
_BLOCKED_TITLES = ("just a moment", "attention required", "access denied")


class InvestingBlocked(Exception):
    """Cloudflare 챌린지를 못 넘었다(제목이 'Just a moment...' 등)."""


@dataclass(frozen=True)
class InvestingRow:
    report_date: date
    company: str
    ticker: str
    eps: str
    eps_forecast: str
    revenue: str
    revenue_forecast: str
    market_cap: str
    timing: str        # 'Before Market' | 'After Market' | ''


def parse_company_ticker(text: str) -> tuple[str, str]:
    """'Palantir(PLTR)Palantir' → ('Palantir', 'PLTR')."""
    # 실측(2026-09-27): 지금은 'Inventiva ( IVA )' 처럼 괄호 안에 공백이 있다 — 원본 정규식은 이걸 못 읽어 0행이 됐다
    m = re.search(r"^(.+?)\(\s*([A-Za-z0-9._-]+)\s*\)", text or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else ((text or "").strip(), "")


_HEADER = re.compile(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), ([A-Z][a-z]+ \d{1,2}, \d{4})$")


def header_date(text: str) -> date | None:
    """'Wednesday, August 26, 2026' → date. 머리행이 아니면 None."""
    from datetime import datetime
    m = _HEADER.match((text or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date()
    except ValueError:
        return None


def parse_value(v: str) -> str:
    """'0.25/' → '0.25', '-/' → ''."""
    v = (v or "").replace("/", "").strip()
    return "" if v in ("-", "") else v


def rows_from_cells(cells: list[str], path_count: int, day: date) -> InvestingRow | None:
    """표 한 줄(셀 글자들 · 시각 칸 SVG path 수) → 행. 날짜 구분 행 · 티커 없는 행은 None.

    실제 칸 순서: [빈칸, 회사(티커), EPS/, EPS 컨센, 매출/, 매출 컨센, 시가총액, 시각, …]
    시각은 아이콘으로만 온다 — 해(path 4개) = 장전, 달(path 1개) = 장후(원본 판별법).
    """
    cells = [c.strip() for c in cells]
    if len(cells) < 6 or not cells[1] or cells[1].count(",") >= 2:
        return None
    company, ticker = parse_company_ticker(cells[1])
    if not ticker:
        return None
    timing = "Before Market" if path_count == 4 else "After Market" if path_count == 1 else ""
    return InvestingRow(day, company, ticker, parse_value(cells[2]), parse_value(cells[3]), parse_value(cells[4]),
                        parse_value(cells[5]), parse_value(cells[6]) if len(cells) > 6 else "", timing)


def crawl_dates(days: list[date], *, on_day=None, launch_timeout_ms: int = 90000) -> dict[date, list[InvestingRow]]:
    """날짜마다 그날 발표 목록. Cloudflare 에 막히면 `InvestingBlocked`.

    `on_day(day, rows)` — 하루 끝날 때마다 바로 부른다(호출 쪽이 그날 몫을 즉시 저장하게).
    ⚠️2026-10-04: 드라이버가 `write EINVAL` 로 죽고 3시간 상한까지 굳어 모은 날짜가 전부 날아갔다.
      크롬은 **한 회차에 한 번만** 띄운다(사용자 요구 — Cloudflare 때문에 시도 수를 줄인다). 쪼개 띄우거나 재시도를 늘리지 말 것.
    """
    from playwright.sync_api import sync_playwright

    out: dict[date, list[InvestingRow]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=False, slow_mo=50,
            args=["--disable-dev-shm-usage", "--disable-extensions", "--disable-gpu",
                  "--disable-blink-features=AutomationControlled", "--window-position=-32000,-32000"],
        )
        try:
            page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
            for attempt in range(3):
                try:
                    page.goto(URL, wait_until="domcontentloaded", timeout=launch_timeout_ms)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(3)
            # Cloudflare 챌린지는 몇 초 뒤 스스로 풀리기도 한다 — 표가 뜰 때까지 기다려 보고 판정
            try:
                page.wait_for_selector(_TABLE, timeout=25000)
            except Exception:
                pass
            if any(t in (page.title() or "").lower() for t in _BLOCKED_TITLES) or page.locator(_TABLE).count() == 0:
                raise InvestingBlocked(f"Cloudflare 통과 실패 — 제목 '{page.title()}'")
            # ★2026-10-28: 표 선택자는 자리표시 행에도 바로 맞는다 — 첫 표가 실제로 찰 때까지 기다린 뒤 날짜를 바꾼다
            #   (실측: 열고 2초 뒤에 찼다). 로드 중에 날짜를 바꾸면 첫 날짜가 빈손으로 끝날 수 있다.
            started = time.monotonic()
            while time.monotonic() - started < SETTLE_TIMEOUT and not any(_hdr(x) for x in _read_raw(page)):
                time.sleep(SETTLE_POLL)
            _block_noise(page)
            _cookie(page)
            for day in days:
                out[day] = _one_day(page, day)
                if on_day is not None:
                    on_day(day, out[day])
                time.sleep(1 + random.random())          # 서버 부하 방지(원본)
        finally:
            browser.close()
    return out


def _block_noise(page) -> None:
    noisy = ("googletagmanager", "google-analytics", "doubleclick", "facebook", "twitter", "amazon-adsystem",
             "adsystem", "adservice", "googlesyndication", "chartbeat", "scorecardresearch", "taboola", "outbrain")

    def route(r):
        req = r.request
        if req.resource_type in ("image", "media", "font") or any(d in req.url for d in noisy):
            r.abort()
        else:
            r.continue_()

    page.route("**/*", route)


def _cookie(page) -> None:
    try:
        b = page.locator("button#onetrust-accept-btn-handler")
        if b.is_visible(timeout=3000):
            b.click()
            time.sleep(1)
    except Exception:
        pass


# ★2026-10-28: 날짜를 바꾼 뒤 '1.5초 고정 대기'를 버리고, **요청한 날의 표가 다 찼는지** 보고 읽는다.
#   실측(10-29 표, 사용자 승인 1회 진단): 적용 후 1.5·3·5·8초에는 종목 없는 자리표시 35행뿐이었고, 12초에야
#   223행이 찼다. 고정 1.5초로 읽으면 자리표시·반쯤 찬 표를 읽어 매출 컨센이 거의 매칭되지 않았다
#   (10-22~28 회차당 신규 0~2건, rows_seen 이 같은 날짜에도 크게 흔들림).
SETTLE_TIMEOUT = 45.0   # 이 시간 안에 안정되지 않으면 그때까지 본 표로 판정한다(날짜가 안 바뀌었으면 아래에서 재시도)
#   ⚠️2026-10-28 실측: 10-29 표는 적용 후 13.2초, 10-30 은 4.1초에 찼다. 25초로는 서버가 느린 날 놓쳤다(1일치 확인 0행).
SETTLE_POLL = 1.0
SETTLE_REPEATS = 3      # 그날 행 수가 연속 3번 같으면 다 찬 것으로 본다

_READ_ROWS = """(sel) => {
    const t = document.querySelector(sel);
    if (!t) return [];
    return [...t.querySelectorAll('tbody tr')].map(tr => {
        const tds = [...tr.querySelectorAll('td')];
        return {cells: tds.map(td => td.innerText.replace(/\\s+/g, ' ').trim()),
                paths: tds[7] ? tds[7].querySelectorAll('path').length : 0};
    });
}"""


def _hdr(x: dict) -> date | None:
    cells = x.get("cells") or []
    return header_date(cells[1] if len(cells) > 1 else "")


def day_count(raw: list[dict], day: date) -> int | None:
    """표에서 `day` 머리행 아래 종목 행 수. 그날 머리행이 아직 없으면 None(자리표시·옛 날짜 표)."""
    seen, count, current = False, 0, None
    for x in raw:
        h = _hdr(x)
        if h:
            current = h
            seen = seen or h == day
            continue
        if current == day and len(x.get("cells") or []) > 1 and parse_company_ticker(x["cells"][1])[1]:
            count += 1
    return count if seen else None


def settled(counts: list[int | None], repeats: int = SETTLE_REPEATS) -> bool:
    """그날 머리행이 보이고, 그날 행 수가 마지막 `repeats` 번 연속 같으면 다 찼다."""
    tail = counts[-repeats:]
    return len(tail) == repeats and tail[0] is not None and all(c == tail[0] for c in tail)


def _read_raw(page) -> list[dict]:
    # ⚠️`textContent` 는 빈 글자로 온다(실측) — `innerText` 로, 한 번의 스크립트로 모든 행을 읽는다
    return page.evaluate(_READ_ROWS, _TABLE)


def _wait_settled(page, day: date) -> list[dict]:
    started, counts, raw = time.monotonic(), [], []
    while time.monotonic() - started < SETTLE_TIMEOUT:
        time.sleep(SETTLE_POLL)
        raw = _read_raw(page)
        counts.append(day_count(raw, day))
        if settled(counts):
            break
    return raw


def rows_for_day(raw: list[dict], day: date) -> list[InvestingRow]:
    """★행의 날짜는 **표 안의 날짜 머리행**('Wednesday, August 26, 2026')으로 정한다 — 요청한 날로 붙이면,
    날짜 바꾸기가 조용히 실패했을 때 옛 표의 행이 엉뚱한 날짜로 들어간다(실측: 긴 회차에서 NVDA 8/26 누락)."""
    rows, current = [], None
    for x in raw:
        h = _hdr(x)
        if h:
            current = h
            continue
        if current == day:
            r = rows_from_cells(x["cells"], x["paths"], day)
            if r:
                rows.append(r)
    return rows


def _one_day(page, day: date) -> list[InvestingRow]:
    mmddyyyy = day.strftime("%m/%d/%Y")
    for attempt in range(3):
        try:
            page.keyboard.press("Escape")                              # 로그인 팝업 닫기(원본 방법 1)
            btn = page.locator("button:has(span:text('Custom dates'))")
            btn.wait_for(state="visible", timeout=10000)
            btn.click()
            time.sleep(0.5)
            # ⚠️원본의 React native setter 주입은 지금 먹지 않는다(실측 2026-09-27: 표가 기본 주간 그대로) —
            #   Playwright `fill` 이 실제 입력 이벤트를 내서 반영된다
            page.locator("#date-picker-start-day").fill(mmddyyyy)
            page.locator("#date-picker-end-day").fill(mmddyyyy)
            time.sleep(0.5)
            apply = page.locator("[data-test='date-picker-apply']")
            apply.wait_for(state="visible", timeout=5000)
            apply.click(force=True)
            time.sleep(1)
            if page.locator("#date-picker-start-day").is_visible():
                page.keyboard.press("Enter")
            raw = _wait_settled(page, day)
            if day_count(raw, day) is None:
                # 그날 머리행이 끝내 안 보였다 — 다른 날짜 표가 남았거나(날짜 바꾸기 실패) 자리표시 행뿐(아직 로드 중)이면
                # 다시 시도한다. ⚠️자리표시만 보고 '그날 발표 없음'으로 끝내면 안 된다(10-28 1일치 확인에서 0행이 된 원인).
                if raw and attempt < 2:
                    raise RuntimeError(f"표가 {day} 로 바뀌지 않음")        # 다시 시도
                return []
            return rows_for_day(raw, day)
        except Exception:
            if attempt == 2:
                raise
            page.keyboard.press("Escape")
            time.sleep(1)
    return []
