"""계절성 C4 — API 모양·근거 표시·연도별 칸."""
import math

from app.models import MonthlyClose, SeasonalitySeries


def _seed(db, years=20):
    db.add(SeasonalitySeries(key="SPX", label="S&P 500", grp="index", yahoo_symbol="^GSPC", sort=0))
    db.add(SeasonalitySeries(key="ChiNext", label="창업판", grp="index", yahoo_symbol=None,
                             continuation="frozen", sort=1))
    db.commit()
    price = 100.0
    for y in range(2000, 2000 + years):
        for m in range(1, 13):
            # 10월만 매년 +5%, 나머지는 +0.5% — 10월 칸이 뚜렷해야 한다
            price *= 1.05 if m == 10 else 1.005 + (0.002 if y % 2 else -0.002)
            key = f"{y:04d}-{m:02d}"
            db.add(MonthlyClose(series="SPX", month=key, close=price, source="bloomberg"))
            db.add(MonthlyClose(series="ChiNext", month=key, close=price, source="bloomberg"))
    db.commit()


def test_seasonality_shape_and_evidence(client, db):
    _seed(db)
    body = client.get("/api/v1/market/seasonality", params={"window": "전구간"}).json()
    g = body["groups"]["index"]
    assert g["last_month"] == "2019-12" and g["signal_month"] == "2020-01"
    assert {s["key"] for s in g["series"]} == {"SPX", "ChiNext"}
    assert len(g["cells"]) == 24                              # 2 시계열 × 12 개월
    oct_cell = next(c for c in g["cells"] if c["series"] == "SPX" and c["month"] == 10)
    assert math.isclose(oct_cell["mean"], 5.0) and oct_cell["win_rate"] == 100.0
    sig = {s["series"]: s for s in g["signals"]}
    assert sig["ChiNext"]["continuation"] == "frozen"         # 화면이 '갱신 중단' 을 단다
    assert isinstance(sig["SPX"]["evidence"], bool)           # '근거 없음' 을 따로 셀 수 있다
    bt = g["backtest"]
    assert set(bt) == {"상승", "중립", "하락", "항상상승"}     # 기준선이 같이 온다


def test_unknown_window_rejected(client, db):
    assert client.get("/api/v1/market/seasonality", params={"window": "3년"}).status_code == 400


def test_cell_returns_yearly_values(client, db):
    _seed(db, years=5)
    body = client.get("/api/v1/market/seasonality/cell", params={"series": "SPX", "month": 10}).json()
    assert [y["year"] for y in body["years"]] == [2000, 2001, 2002, 2003, 2004]
    assert all(math.isclose(y["ret"], 5.0) for y in body["years"])
    assert client.get("/api/v1/market/seasonality/cell",
                      params={"series": "NOPE", "month": 1}).status_code == 404
