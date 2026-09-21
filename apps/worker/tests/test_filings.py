"""SEC 공시 분류.

여기서 지키려는 것은 하나다 — **서류 더미가 중요한 공시를 덮지 않는다.**
실측(NVDA 최근 1001건): Form 4 556 + Form 144 247 = 803건이 임원 서류고,
읽을 만한 건 8-K 62 · 10-Q 19 · 10-K 6 뿐이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.filings import (  # noqa: E402
    CATEGORY_EVENT,
    CATEGORY_INSIDER,
    CATEGORY_OTHER,
    CATEGORY_OWNERSHIP,
    CATEGORY_RESULTS,
    form_category,
    form_label,
    item_label,
    normalize_form,
)


def test_amended_forms_stay_in_their_category():
    """`/A`(정정)를 표에 일일이 넣지 않는다 — 규칙으로 처리한다.

    실측에서 `4/A`·`3/A`·`144/A` 가 매핑에 없어 **내부자 서식 13건이 '기타'로
    새고** 있었다. 표를 늘리는 방식은 썩는다.
    """
    for form in ("4/A", "3/A", "144/A", "5/A"):
        assert form_category(form) == CATEGORY_INSIDER, form
    assert form_category("10-K/A") == CATEGORY_RESULTS
    assert form_category("8-K/A") == CATEGORY_EVENT
    # 정정이라는 사실 자체는 이름에 남는다.
    assert form_label("10-Q/A") == "분기보고서 (정정)"
    assert form_label("10-Q") == "분기보고서"


def test_sec_spells_the_same_form_two_ways():
    """SEC 는 `SC 13G` 와 `SCHEDULE 13G` 를 둘 다 쓴다.

    실측: 보유 종목 최근 1년에서 SCHEDULE 13G/A 48건, SCHEDULE 13G 21건.
    """
    assert normalize_form("SCHEDULE 13G")[0] == "SC 13G"
    assert normalize_form("SCHEDULE 13D/A") == ("SC 13D", True)
    assert form_category("SCHEDULE 13G/A") == CATEGORY_OWNERSHIP
    assert form_category("SC 13G") == CATEGORY_OWNERSHIP


def test_424b_variants_collapse_to_one_family():
    """424B2/B3/B5/B7 은 전부 같은 성격의 최종 설명서다."""
    for form in ("424B2", "424B3", "424B5", "424B7"):
        assert normalize_form(form)[0] == "424B", form
        assert form_category(form) == CATEGORY_EVENT, form


def test_unknown_form_keeps_its_code_and_is_not_invented():
    """모르는 서식에 **이름을 지어내지 않는다.** 코드 그대로 두고 기타로 보낸다."""
    assert form_label("XYZ-9") == "XYZ-9"
    assert form_category("XYZ-9") == CATEGORY_OTHER


def test_item_codes_become_korean_but_unknown_codes_stay_numeric():
    """`8-K 2.02` 는 아무 뜻도 전달하지 못한다 — "실적 발표"여야 한다."""
    assert item_label("2.02") == "실적 발표"
    assert item_label("5.02") == "임원 선임·사임"
    assert item_label("1.05") == "사이버 보안 사고"
    # 모르는 코드는 지어내지 않는다.
    assert item_label("9.99") == "9.99"


def test_insider_forms_are_classified_apart_from_everything_else():
    """내부자 서식은 별도 분류다 — 나열 대상에서 빠져야 하기 때문이다."""
    for form in ("3", "4", "5", "144"):
        assert form_category(form) == CATEGORY_INSIDER, form
    # 임원이 낸다고 다 내부자 서식은 아니다. 8-K 5.02 는 회사가 내는 수시보고다.
    assert form_category("8-K") == CATEGORY_EVENT
