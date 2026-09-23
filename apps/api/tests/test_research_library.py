"""리서치 자료 인덱싱.

지키는 것: **내용은 읽지 않는다**, **지정한 폴더 밖으로 안 나간다**,
**자른 것을 조용히 숨기지 않는다**.
"""

import os
from pathlib import Path

from app.core import research_library as rl


def _touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_unset_root_is_not_a_problem(tmp_path):
    """경로를 아직 안 정한 것은 **오류가 아니다.** 화면이 안내만 하면 된다."""
    lib = rl.scan(None)
    assert lib.configured is False
    assert lib.problem is None
    assert lib.documents == []


def test_missing_root_says_why(tmp_path):
    """정했는데 없으면 **이유를 말한다.** 빈 목록으로 두면 자료가 없는 줄 안다."""
    lib = rl.scan(str(tmp_path / "없는폴더"))
    assert lib.configured is True
    assert lib.problem is not None
    assert lib.documents == []


def test_only_research_extensions(tmp_path):
    """리서치 자료만 센다. 스크린샷·집파일까지 세면 목록이 안 읽힌다."""
    _touch(tmp_path / "반도체 전망.pdf")
    _touch(tmp_path / "메모.md")
    _touch(tmp_path / "사진.png")
    _touch(tmp_path / "자료.zip")

    names = {d.name for d in rl.scan(str(tmp_path)).documents}
    assert names == {"반도체 전망.pdf", "메모.md"}


def test_hidden_and_office_temp_files_are_skipped(tmp_path):
    """`~$` 로 시작하는 오피스 임시 파일은 자료가 아니다."""
    _touch(tmp_path / "보고서.docx")
    _touch(tmp_path / "~$보고서.docx")
    _touch(tmp_path / ".숨김.pdf")

    assert [d.name for d in rl.scan(str(tmp_path)).documents] == ["보고서.docx"]


def test_symlink_outside_the_root_is_dropped(tmp_path):
    """⚠️**지정한 폴더 밖으로 나가지 않는다.**

    링크를 따라가면 홈 디렉터리를 통째로 훑을 수 있다. 실경로가 뿌리 안인지
    확인하고 아니면 버린다.
    """
    outside = _touch(tmp_path / "바깥" / "비밀.pdf")
    root = tmp_path / "리서치"
    root.mkdir()
    try:
        os.symlink(outside, root / "링크.pdf")
    except (OSError, NotImplementedError):  # 권한 없는 환경
        return

    assert rl.scan(str(root)).documents == []


def test_tickers_come_from_the_file_name_only(tmp_path):
    """파일 이름에서 보유 종목을 찾는다 — **내용은 열지 않는다.**"""
    _touch(tmp_path / "NVDA 3분기 리뷰.pdf", "이 안에는 MSFT 가 잔뜩 있다")
    holdings = {"NVDA": "엔비디아", "MSFT": "마이크로소프트"}

    doc = rl.scan(str(tmp_path), holdings).documents[0]
    assert doc.tickers == ["NVDA"]  # 내용의 MSFT 는 모른다


def test_korean_name_also_matches(tmp_path):
    """한글 이름으로 된 파일도 잡는다 — 자료 제목은 보통 한글이다."""
    _touch(tmp_path / "엔비디아 실적 정리.pdf")
    doc = rl.scan(str(tmp_path), {"NVDA": "엔비디아"}).documents[0]
    assert doc.tickers == ["NVDA"]


def test_short_ticker_does_not_match_inside_a_word(tmp_path):
    """⚠️짧은 티커가 낱말 속에 걸리면 안 된다.

    BE(블룸 에너지)를 부분 문자열로 찾으면 "BEST", "ROBERT" 가 전부 걸린다.
    낱말 경계로 본다.
    """
    _touch(tmp_path / "BEST PRACTICES.pdf")
    _touch(tmp_path / "BE 실적.pdf")
    holdings = {"BE": "블룸 에너지"}

    by_name = {d.name: d.tickers for d in rl.scan(str(tmp_path), holdings).documents}
    assert by_name["BEST PRACTICES.pdf"] == []
    assert by_name["BE 실적.pdf"] == ["BE"]


def test_truncation_is_reported(tmp_path, monkeypatch):
    """⚠️조용히 자르면 "자료가 이게 다"로 읽힌다. 잘랐으면 말한다."""
    monkeypatch.setattr(rl, "MAX_FILES", 3)
    for i in range(6):
        _touch(tmp_path / f"자료{i}.pdf")

    lib = rl.scan(str(tmp_path))
    assert lib.truncated is True
    assert len(lib.documents) == 3


def test_newest_first(tmp_path):
    """안 읽은 자료를 먼저 보게 — 최근 수정순."""
    old = _touch(tmp_path / "옛날.pdf")
    new = _touch(tmp_path / "최근.pdf")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    os.utime(new, (1_700_000_000, 1_700_000_000))

    assert [d.name for d in rl.scan(str(tmp_path)).documents] == ["최근.pdf", "옛날.pdf"]
