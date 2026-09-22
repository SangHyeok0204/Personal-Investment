"""시드가 증권사가 준 사실과 어긋나지 않는지 검사한다.

근거는 둘이다 — **증권사가 준 종목명**(화면에 보이는 것이므로 우선)과 **SEC
법인명**. 둘 다 없으면 '확인 불가'로 센다.

★왜 필요한가: `etf_exposure.py` 에 "TSL 은 TSLA **2배**"라고 적어 두었는데
  증권사 종목명은 "테슬라 **1.25배** 레버리지 그래닛셰어즈 ETF" 였다. TSL
  (그래닛셰어즈 1.25배)과 TSLL(디렉시온 2배)을 한 줄에 묶어 같은 근거를 적은
  것이 화근이었다. 한 번 눈으로 훑어 고쳤지만 **다음에 또 틀린다** — 종목을
  새로 사면 그때 또 손으로 확인해야 하기 때문이다. 그래서 스크립트로 만든다.

⚠️검사할 수 있는 것과 없는 것을 **구분해서 센다.** 증권사 이름이 없는 티커는
  '맞다'가 아니라 **'확인 불가'** 다. 통과 건수에 섞으면 검증됐다고 착각한다.

사용: .venv/bin/python scripts/audit_seeds.py
      (DB 주소는 `.env.local` 에서 읽는다 — README 'Docker 없이 로컬에서 직접 돌리기')
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import text  # noqa: E402

from app.core.portfolio_character import multiplier_from_name  # noqa: E402
from app.db.session import engine  # noqa: E402

#: 노출 라벨 → 종목명에 나와야 할 낱말(하나라도 있으면 통과).
#: ⚠️여기 없는 라벨은 '확인 불가'로 센다 — 아무 말이나 통과시키지 않는다.
EXPECTED_WORDS: dict[str, tuple[str, ...]] = {
    "컴퓨팅 인프라": ("반도체", "SEMICONDUCTOR", "칩"),
    "하드웨어 활용": ("테슬라", "TESLA"),
    "전통 산업": ("원자재", "소재", "금융", "MATERIAL", "FINANCIAL", "SECTOR"),
    "에너지 인프라": ("에너지", "유틸리티", "ENERGY", "UTIL"),
    "실물자산": ("금", "은", "GOLD", "SILVER"),
    "가상자산": ("비트코인", "이더리움", "BITCOIN", "ETHER"),
    "채권·현금성": ("국채", "TREASURY", "BOND"),
    "분산 (다중 섹터)": ("배당주", "S&P", "QQQ", "나스닥", "DIVIDEND"),
}


def load_seed():
    path = ROOT / "database" / "seeds" / "etf_exposure.py"
    spec = importlib.util.spec_from_file_location("_seed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sec_names() -> dict[str, str]:
    """SEC 에 등록된 법인명. **두 번째 근거**다.

    ⚠️개별 ETF 가 신탁(iShares Trust 등) 아래 묶여 있으면 티커로 안 나온다 —
      그건 '틀렸다'가 아니라 여전히 '확인 불가'다.
    ⚠️네트워크가 막혀도 검사를 죽이지 않는다. 근거가 하나 줄 뿐이다.
    """
    sys.path.insert(0, str(ROOT / "apps" / "worker"))
    try:
        from prices.filings import fetch_cik_map

        return {t: title for t, (_cik, title) in fetch_cik_map().items() if title}
    except Exception:
        return {}


def broker_names() -> dict[str, list[str]]:
    """증권사가 준 종목명. 한 티커에 표기가 여러 개일 수 있다."""
    sql = text(
        """
        SELECT ticker, asset_name FROM trades WHERE asset_name IS NOT NULL
        UNION SELECT ticker, asset_name FROM realized_pnl WHERE asset_name IS NOT NULL
        UNION SELECT ticker, asset_name FROM dividends WHERE asset_name IS NOT NULL
        UNION SELECT ticker, name FROM assets WHERE name IS NOT NULL
        """
    )
    out: dict[str, list[str]] = {}
    with engine.connect() as conn:
        for ticker, name in conn.execute(sql):
            out.setdefault(ticker.upper(), []).append(name)
    return out


def main() -> int:
    seed = load_seed()
    names = broker_names()
    sec = sec_names()
    if not sec:
        print("(SEC 목록을 받지 못했다 — 증권사 이름만으로 검사한다)\n")

    def evidence(ticker: str) -> tuple[list[str], str] | tuple[None, None]:
        """이 티커의 근거와 출처. 증권사 이름이 먼저다(화면에 보이는 것이므로)."""
        if ticker in names:
            return names[ticker], "증권사"
        if ticker in sec:
            return [sec[ticker]], "SEC"
        return None, None
    problems: list[str] = []
    unverifiable: list[str] = []
    checked = 0

    print("[레버리지 배수]")
    for ticker, (mult, why) in sorted(seed.ETF_LEVERAGE.items()):
        found, origin = evidence(ticker)
        if not found:
            unverifiable.append(f"{ticker} 배수 (증권사·SEC 어느 쪽에도 이름 없음)")
            continue
        # 이름 여러 개 중 하나라도 배수를 말하면 그걸 쓴다.
        from_name = next(
            (m for m in (multiplier_from_name(n) for n in found) if m is not None),
            None,
        )
        if from_name is None:
            unverifiable.append(f"{ticker} 배수 (이름에 'N배'가 없음: {found[0]})")
            continue
        checked += 1
        if str(from_name) == mult or float(from_name) == float(mult):
            print(f"  OK {ticker}: {mult}배 — {found[0]} [{origin}]")
        else:
            print(f"  X  {ticker}: 시드 {mult}배 vs 이름 {from_name}배 — {found[0]}")
            problems.append(f"{ticker} 배수 (시드 {mult} vs 이름 {from_name})")

    print("\n[노출 라벨]")
    for ticker, (label, why) in sorted(seed.ETF_EXPOSURE.items()):
        found, origin = evidence(ticker)
        if not found:
            unverifiable.append(f"{ticker} 노출 (증권사·SEC 어느 쪽에도 이름 없음)")
            continue
        words = EXPECTED_WORDS.get(label)
        if words is None:
            unverifiable.append(f"{ticker} 노출 (라벨 '{label}' 의 기대 낱말 미정의)")
            continue
        checked += 1
        joined = " ".join(found).upper()
        if any(w.upper() in joined for w in words):
            print(f"  OK {ticker}: {label} — {found[0]} [{origin}]")
        else:
            print(f"  ?  {ticker}: {label} 인데 이름에 {words} 가 없다 — {found[0]} [{origin}]")
            problems.append(f"{ticker} 노출 ({label} vs '{found[0]}')")

    # ── 보유·거래한 ETF 인데 시드에 없는 것 ────────────────────────────────
    print("\n[시드에 없는 ETF]")
    missing = [
        t for t, n in sorted(names.items())
        if t not in seed.ETF_EXPOSURE and any("ETF" in x.upper() for x in n)
    ]
    if missing:
        for t in missing:
            print(f"  !  {t}: 거래했는데 시드에 없다 — {names[t][0]}")
            problems.append(f"{t} 시드 누락")
    else:
        print("  OK 없음")

    print(f"\n{'=' * 60}")
    print(f"검증 {checked}건 · 확인 불가 {len(unverifiable)}건 · 문제 {len(problems)}건")
    if unverifiable:
        print("\n확인 불가 (증권사 이름이 없어 대조할 수 없다 — '맞다'가 아니다):")
        for item in unverifiable:
            print(f"  ·  {item}")
    if problems:
        print("\n문제:")
        for item in problems:
            print(f"  X  {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
