"""화면에 적을 종목 이름을 한 군데서 정한다.

★왜 필요한가: 같은 종목이 화면마다 다른 이름으로 보였다.

      SOXL   보유 종목·배분: "미국 반도체 3배 디렉시온 ETF"
             편입비·수수료:   "미국반도체3배디렉시온ETF"
      GLD    보유 종목:      "금 SPDR ETF"
             편입비·수수료:   "SPDRGOLDSHARESHKD"

  원인은 **어느 표에서 이름을 꺼냈느냐**다. `current_positions` 쪽 화면은
  `assets.name`(우리가 정리한 이름)을 쓰고, 체결 원장 쪽 화면은
  `trades.asset_name`(증권사가 준 날것)을 쓴다. 날것은 띄어쓰기가 없고 가끔
  영문 원명이라, 사용자는 **다른 종목으로 읽는다.**

  한 화면씩 고치면 다음에 만드는 화면에서 또 틀린다. 그래서 여기 모은다.

★뿌리 원인은 **증권사 TR 마다 이름 형식이 다르다**는 것이다.
    잔고 TR(`frgn_stk_nm`)   → "미국 반도체 3배 디렉시온 ETF"   (띄어쓰기 있음)
    실현손익 TR(`asset_name`) → "미국 초단기 국채 아이셰어즈 ETF" (띄어쓰기 있음)
    체결 TR(`asset_name`)     → "미국초단기국채아이셰어즈ETF"     (없음)
  우리가 고칠 수 있는 것은 **어느 것을 먼저 쓰느냐** 뿐이다.

⚠️`assets` 에는 **지금 들고 있는 종목만** 있다(실측 17행). 이미 판 종목은
  포지션이 없어 자산 표에 안 남는다 — 매매한 25종목 중 8종목(AVGO·MNST·
  QCOM·QLD·SGOV·SKHY·SNDK·TSLL)이 그렇다. 그래서 **실현손익 표를 두 번째
  원천으로 본다.** 그 8종목 전부 거기에 띄어쓰기 있는 이름이 있다.

⚠️그래도 못 찾는 티커는 호출한 쪽이 원장 이름으로 떨어져야 하므로,
  여기서는 **찾은 것만** 돌려준다 — 없는 이름을 지어내지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, RealizedPnl


def display_names(db: Session, tickers: Iterable[str]) -> dict[str, str]:
    """티커 → 화면에 적을 이름. 어디에도 없는 티커는 **빠진다.**

    쓰는 쪽은 이렇게 떨어뜨린다::

        names = display_names(db, tickers)
        label = names.get(ticker) or ledger_name or ticker

    ⚠️`or` 순서를 뒤집지 말 것. 원장 이름이 앞에 오면 자산 표에 있는 종목까지
      날것으로 찍힌다 — 실제로 그렇게 돼 있었다.
    """
    wanted = {t for t in tickers if t}
    if not wanted:
        return {}

    # 실현손익 표를 먼저 깔고 자산 표로 덮는다 — 보유 중인 종목은 잔고 TR 이름이
    # 최신이다(이름이 바뀌면 잔고 쪽이 먼저 반영된다).
    names: dict[str, str] = {
        ticker: name
        for ticker, name in db.execute(
            select(RealizedPnl.ticker, RealizedPnl.asset_name).where(
                RealizedPnl.ticker.in_(wanted)
            )
        ).all()
        if name
    }
    names.update(
        {
            ticker: name
            for ticker, name in db.execute(
                select(Asset.ticker, Asset.name).where(Asset.ticker.in_(wanted))
            ).all()
            if name
        }
    )
    return names


# ── 우리 표에 없는 티커: 네이버 증권 자동완성에서 이름을 받는다 ─────────────────
# ★관심종목에 티커만 넣으면 이름이 비어 "ISRG [ISRG]" 처럼 보였다. 자산·실현손익
#   표에는 **사고판 종목만** 있으니, 처음 보는 티커는 밖에서 받아야 한다.
# ⚠️토스 `/api/v1/stocks` 도 이름을 주지만 IP 허용목록에 막히면 통째로 실패한다
#   (2026-09-27 실측). 네이버는 키가 필요 없고, 이미 쓰는 이름("블룸 에너지",
#   "알파벳 Class A")과 같은 한글 표기를 준다.
_NAVER_AC = "https://ac.stock.naver.com/ac"
_NAVER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)


def parse_naver_ac(body: dict, ticker: str) -> str | None:
    """자동완성 응답에서 **코드가 정확히 같은** 항목의 이름만 고른다.

    ⚠️첫 항목을 그냥 쓰면 안 된다 — "BE" 를 치면 BRK B 도 함께 온다.
    """
    want = ticker.strip().upper()
    for item in (body or {}).get("items") or []:
        if str(item.get("code") or "").strip().upper() == want:
            name = str(item.get("name") or "").strip()
            return name or None
    return None


def lookup_name(ticker: str, timeout: float = 5.0) -> str | None:
    """네이버에서 이름을 받는다. 실패하면 None — 화면이 티커로 떨어진다."""
    import httpx

    try:
        response = httpx.get(
            _NAVER_AC,
            params={"q": ticker, "target": "stock,etf"},
            timeout=timeout,
            headers={"User-Agent": _NAVER_UA, "Accept": "application/json"},
        )
        response.raise_for_status()
        return parse_naver_ac(response.json(), ticker)
    except (httpx.HTTPError, ValueError):
        return None
