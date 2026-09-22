"""체결 원장의 날짜가 주문일보다 며칠 뒤인지 잰다 — 매매일지 창의 근거.

★왜 필요한가: `trades.trade_date` 는 **체결일이 아니라 결제일(T+2)** 이다.
  매매일지가 "적어 둔 계획이 실제로 체결됐나"를 보려면 창을 얼마나 열어 둘지
  정해야 하는데, 그 숫자를 눈대중으로 두면 계획이 "체결 0주"로 조용히 적힌다.
  실제로 그렇게 적힌 적이 있다.

⚠️**(티커, 방향, 수량)으로 조인하면 안 된다.** 같은 조합이 여러 번 나온다 —
  이 계좌만 해도 SCHD 10주 매수가 6번이다. 그대로 조인하면 한 체결이 여러
  주문에 붙어 **있지도 않은 6·8·10·12일 꼬리**가 생긴다. 실제로 그 잘못된
  측정으로 창을 정할 뻔했다. 쓴 체결을 다시 쓰지 않도록 **일대일**로 짝짓는다.

⚠️짝을 못 찾는 주문이 남는 것은 **정상이다.** 증권사가 같은 날 같은 종목
  주문을 한 줄로 합쳐 결제한다(실측: 09-14 에 EETH 2주·32주를 따로 주문했는데
  체결은 09-16 에 34주 한 줄). 그래서 매매일지는 수량으로 짝짓지 않고 창 안의
  같은 방향 체결을 모두 더한다.

사용: .venv/bin/python scripts/measure_settlement_lag.py
      (DB 주소는 `.env.local` 에서 읽는다 — README 참고)
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402

#: 매매일지가 실제로 쓰는 창. 어긋나면 알린다.
WINDOW_AFTER = 7
WINDOW_BEFORE = 1


def main() -> int:
    with engine.connect() as conn:
        orders = conn.execute(text("""
            select order_date, ticker, side, filled_quantity
            from orders
            where coalesce(filled_quantity, 0) > 0
            order by order_date, order_no
        """)).all()
        trades = conn.execute(text("""
            select trade_date, ticker, side, quantity
            from trades
            order by trade_date, trade_no
        """)).all()

    # 체결에 **고유 번호**를 붙인다. trade_no 는 날짜마다 다시 매겨져 고유하지 않다.
    buckets: dict[tuple, list] = defaultdict(list)
    for i, (d, ticker, side, qty) in enumerate(trades):
        buckets[(ticker, side, qty)].append((d, i))
    for key in buckets:
        buckets[key].sort()

    used: set[int] = set()
    lags: Counter[int] = Counter()
    unmatched: list[tuple] = []

    for order_date, ticker, side, qty in sorted(orders):
        pick = next(
            (
                (d, i)
                for d, i in buckets.get((ticker, side, qty), [])
                if i not in used and d >= order_date
            ),
            None,
        )
        if pick is None:
            unmatched.append((order_date, ticker, side, qty))
            continue
        used.add(pick[1])
        lags[(pick[0] - order_date).days] += 1

    total = sum(lags.values())
    print(f"주문 {len(orders)}건 · 체결 {len(trades)}건 → 일대일 매칭 {total}건")
    if not total:
        print("잴 것이 없다 — 체결 원장이 비어 있다.")
        return 0

    print()
    cumulative = 0
    for lag in sorted(lags):
        cumulative += lags[lag]
        bar = "█" * max(1, round(lags[lag] / total * 40))
        print(f"  {lag:2d}일 {lags[lag]:4d}건  {cumulative / total * 100:5.1f}%  {bar}")

    worst = max(lags)
    print()
    print(f"가장 늦은 결제: **{worst}일**")

    problems = 0

    # 창이 실측을 덮는가. 창의 기준점은 주문일이 아니라 일지를 적은 날이라
    # 하루 정도 여유가 더 있어야 한다.
    if worst >= WINDOW_AFTER:
        print(
            f"  X  매매일지 창(window_after={WINDOW_AFTER})이 실측({worst}일)을 "
            f"덮지 못한다 — 계획이 '체결 0주'로 적힐 수 있다"
        )
        problems += 1
    else:
        print(
            f"  OK 매매일지 창(window_after={WINDOW_AFTER}) 안에 든다 "
            f"— 여유 {WINDOW_AFTER - worst}일"
        )

    # 대칭 창이었다면 얼마나 놓쳤을지. 이 수치가 창을 비대칭으로 둔 이유다.
    missed = sum(count for lag, count in lags.items() if lag > 3)
    print(
        f"  ·  대칭 ±3일이었다면 {missed}건({missed / total * 100:.0f}%)을 놓친다 "
        f"— 창을 비대칭으로 두는 이유"
    )

    if unmatched:
        print()
        print(f"짝을 못 찾은 주문 {len(unmatched)}건 — 합쳐서 결제된 것으로 보인다:")
        for order_date, ticker, side, qty in unmatched[:10]:
            print(f"  · {order_date} {ticker} {side} {qty}")
        print("  (매매일지는 수량으로 짝짓지 않으므로 이 건들도 체결로 잡힌다)")

    print()
    print("=" * 56)
    print("문제 없음" if problems == 0 else f"문제 {problems}건")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
