"""보유 종목 뉴스 — 검색어·관련성·중복.

여기서 지키려는 것: **관련 없는 기사를 내 종목 뉴스라고 붙이지 않는다.**
실측(2026-09-22, 10종목 각 100건에서 제목 언급 비율):
    영문 법인명 97.3% · 티커 96.1% · 한국어 82.8%(최저 32% HUT)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.news import _relevant, search_name, title_key  # noqa: E402


def test_legal_suffixes_are_stripped_repeatedly():
    """한 번만 벗기면 남는다 — "Nebius Group N.V." 는 두 번 벗겨야 한다.

    실측: `"Nebius N.V" stock` 은 33건, `"Nebius" stock` 은 100건.
    """
    assert search_name("Nebius Group N.V.") == "Nebius"
    assert search_name("NVIDIA CORP") == "NVIDIA"
    assert search_name("Bloom Energy Corp") == "Bloom Energy"
    assert search_name("Hut 8 Corp.") == "Hut 8"


def test_registration_marks_are_cut():
    """`/NY` 같은 등록 표기는 기사 제목에 나오지 않는다.

    실측: `"CORNING INC /NY" stock` 14건 → `"CORNING" stock` 100건.
    """
    assert search_name("CORNING INC /NY") == "CORNING"
    assert search_name("Tempus AI, Inc.") == "Tempus AI"
    assert search_name("CoreWeave, Inc.") == "CoreWeave"


def test_a_name_made_only_of_legal_forms_is_not_emptied():
    """전부 벗겨 빈 문자열을 만들지 않는다 — 빈 검색어는 아무거나 물어 온다."""
    assert search_name("Trust") == "Trust"
    assert search_name("") == ""


def test_ticker_match_uses_word_boundaries():
    """⚠️부분 문자열로 찾으면 "BE" 가 "BEST"·"BEFORE" 에 걸린다."""
    assert _relevant("BE stock rises", "BE", None) is True
    assert _relevant("The BEST stock to buy BEFORE 2027", "BE", None) is False


def test_company_name_match_needs_three_letters():
    """두 글자 회사명으로 본문을 긁으면 아무거나 걸린다."""
    assert _relevant("Corning gains 5.9 percent", "GLW", "CORNING") is True
    # 회사명이 너무 짧으면 회사명으로는 매칭하지 않는다(티커 규칙만 남는다).
    assert _relevant("an AI story", "XX", "AI") is False


def test_title_key_ignores_publisher_tails():
    """같은 기사가 꼬리표 때문에 다른 제목으로 온다.

    실측: "Alphabet: An Undervalued Stock…" 과 "… | Morningstar Nordics" 가
    따로 들어와 화면에 두 번 보였다.
    """
    a = "Alphabet: An Undervalued Stock to Buy That Even Warren Buffett Likes"
    b = f"{a} | Morningstar Nordics"
    assert title_key(a) == title_key(b)


def test_title_key_does_not_collapse_different_stories():
    assert title_key("Why Corning Stock Is Up") != title_key("Why Corning Stock Is Down")
