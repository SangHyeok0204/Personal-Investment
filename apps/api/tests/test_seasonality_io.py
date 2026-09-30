"""계절성 C1 — 블룸버그 BDH 엑셀 파서와 '연속한 두 달 쌍' 계산."""
from datetime import datetime

import openpyxl

from app.core.seasonality_io import consecutive_pairs, month_key, parse_bdh_xlsx


def _bdh(path):
    """원본과 같은 모양: 3열 블록(날짜·값·빈칸), 첫 행에 티커, 첫 날짜 칸에 BDH 잔재."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SPX Index", None, None, "HSI Index", None, None, "OTHER Index"])
    ws.append(["#N/A Requesting Data...", None, None, "#N/A Requesting Data...", None, None])
    ws.append([datetime(1964, 7, 31), 84.0, None, datetime(1964, 7, 31), 100.0])
    ws.append([datetime(1964, 8, 31), 81.7, None, datetime(1964, 8, 31), 101.0])
    ws.append([datetime(1964, 9, 30), 84.2, None, None, None])            # 항셍 빈 달
    ws.append([datetime(1964, 10, 30), 84.9, None, datetime(1964, 10, 30), 104.0])
    wb.save(path)


def test_parse_skips_bdh_placeholder_and_unknown_blocks(tmp_path):
    p = tmp_path / "bdh.xlsx"
    _bdh(p)
    got = parse_bdh_xlsx(p, {"SPX Index", "HSI Index"})
    assert set(got) == {"SPX Index", "HSI Index"}        # OTHER 는 요청하지 않았다
    assert got["SPX Index"] == {"1964-07": 84.0, "1964-08": 81.7, "1964-09": 84.2, "1964-10": 84.9}
    assert "1964-09" not in got["HSI Index"]             # 빈 달을 채우지 않는다(보간 금지)


def test_consecutive_pairs_do_not_bridge_gaps():
    # 항셍: 7·8·(9 없음)·10 → 7→8 한 쌍만. 8→10 을 한 달 수익률로 세면 안 된다(§D-0).
    assert consecutive_pairs(["1964-07", "1964-08", "1964-10"]) == 1
    assert consecutive_pairs(["1964-11", "1964-12", "1965-01"]) == 2   # 해를 넘는 연속
    assert consecutive_pairs([]) == 0


def test_month_key_same_for_month_start_and_end():
    # Yahoo 는 월초, 블룸버그는 월말 — 같은 달이면 같은 키.
    assert month_key(datetime(2026, 9, 1)) == month_key(datetime(2026, 9, 30)) == "2026-09"
