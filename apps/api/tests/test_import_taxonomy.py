"""분류 생성기(scripts/valuechain/import_taxonomy.py) — 픽스처 원천 → generated/tx-*.ttl.

지키려는 것(계획 Step 6):
  - 축소판 원천(fixtures/taxonomy_mini/src) → expected/ 와 **바이트 동일**(골든), 2회 실행 동일.
  - `--check` 는 같으면 0, 1바이트라도 다르면 1. 입력 검증 실패 시 아무것도 쓰지 않는다.
  - tx-codes.json 은 추가 전용 — 새 L2 가 생겨도 기존 코드는 그대로.
  - 생성물 + core + bio 복사본이 validate 를 통과(공유 기업 라벨 차이는 허용), 교차 파일 신원 규칙.
★원천 Ongoings 폴더·저장소 storage/ 는 읽지도 쓰지도 않는다(bio.ttl·core.ttl 복사본만 tmp 로).
"""
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import valuechain as vc

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "valuechain" / "import_taxonomy.py"
FIXTURE = Path(__file__).parent / "fixtures" / "taxonomy_mini"
SRC = FIXTURE / "src"
EXPECTED = FIXTURE / "expected"

sys.path.insert(0, str(SCRIPT.parent))
import import_taxonomy as it  # noqa: E402


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"})


def digests(d: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir()) if p.is_file()}


def test_golden_and_deterministic(tmp_path):
    out = tmp_path / "generated"
    r = run("--source", str(SRC), "--out", str(out), "--report")
    assert r.returncode == 0, r.stderr
    assert digests(out) == digests(EXPECTED)              # 바이트 동일(골든)
    first = digests(out)
    shutil.rmtree(out)
    assert run("--source", str(SRC), "--out", str(out)).returncode == 0
    assert digests(out) == first                          # 2회 동일
    # 리포트: 스킵·중복·정규화·티커 변경·레지스트리 밖 L2
    assert "non_US 2 · L1 빈 행 1 · 중복 티커 1" in r.stderr
    assert "BRK/A→BRK.A" in r.stderr and "MOGa→MOG.A" in r.stderr
    assert "IAC→PPLI (People Incorporated)" in r.stderr
    assert "가상 신규 L2 (레지스트리에 없음" in r.stderr


def test_check_detects_drift(tmp_path):
    out = tmp_path / "generated"
    shutil.copytree(EXPECTED, out)
    assert run("--source", str(SRC), "--out", str(out), "--check").returncode == 0
    p = out / "tx-financials.ttl"
    data = bytearray(p.read_bytes())
    data[-2] ^= 1                                         # 1바이트 변조
    p.write_bytes(bytes(data))
    r = run("--source", str(SRC), "--out", str(out), "--check")
    assert r.returncode == 1 and "tx-financials.ttl" in r.stderr
    # tx-codes.json 도 비교 대상 — 지우면 다르다
    shutil.copy(EXPECTED / "tx-financials.ttl", p)
    (out / "tx-codes.json").unlink()
    assert run("--source", str(SRC), "--out", str(out), "--check").returncode == 1
    # --check 는 쓰지 않는다
    assert not (out / "tx-codes.json").exists()


def test_missing_source_exits_2(tmp_path):
    assert run("--out", str(tmp_path)).returncode == 2


def _copy_src(tmp_path) -> Path:
    src = tmp_path / "src"
    shutil.copytree(SRC, src)
    return src


def _append_row(src: Path, row: list[str], isin: str, source: str = "US") -> None:
    with open(src / "outputs" / "Classfication.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerow(row)
    with open(src / "work" / "universe_listings.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"isin": isin, "ticker": row[0], "name": row[1], "source": source}) + "\n")


def test_new_l2_keeps_existing_codes(tmp_path):
    out = tmp_path / "generated"
    shutil.copytree(EXPECTED, out)
    before = json.loads((out / "tx-codes.json").read_text(encoding="utf-8"))
    src = _copy_src(tmp_path)
    # 레지스트리 맨 앞에 새 L2 를 끼워 넣어도(순서 변경) 기존 코드는 재번호되지 않는다.
    reg = src / "work" / "taxonomy_registry.md"
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        "### 2. 금융\n\n", "### 2. 금융\n\n- **디지털자산 수탁** (커스터디): 새 L2.\n"), encoding="utf-8")
    _append_row(src, ["CUST", "Custody Corp. Common Stock", "금융", "디지털자산 수탁", ""], "US0000000037")
    r = run("--source", str(src), "--out", str(out), "--report")
    assert r.returncode == 0, r.stderr
    after = json.loads((out / "tx-codes.json").read_text(encoding="utf-8"))
    for slug, m in before.items():
        for label, code in m.items():
            assert after[slug][label] == code             # 추가 전용
    assert after["financials"]["디지털자산 수탁"] == "F04"   # 다음 번호
    ttl = (out / "tx-financials.ttl").read_text(encoding="utf-8")
    assert 'vc:code "F04" ; vc:order 1 ;' in ttl          # 표시 순서는 레지스트리 순
    # 다른 L1 파일은 바이트 불변(L1별 입력 해시)
    assert (out / "tx-healthcare.ttl").read_bytes() == (EXPECTED / "tx-healthcare.ttl").read_bytes()


@pytest.mark.parametrize("breakage", ["row_count", "misaligned", "bad_l1"])
def test_input_validation_writes_nothing(tmp_path, breakage):
    src = _copy_src(tmp_path)
    csv_path = src / "outputs" / "Classfication.csv"
    if breakage == "row_count":                           # 원천이 쓰는 중(CSV 만 한 줄 더)
        with open(csv_path, "a", encoding="utf-8") as f:
            f.write("ZZZ,Z Corp,금융,예금·대출 은행,\n")
    elif breakage == "misaligned":                        # ticker_changes 로 설명 안 되는 불일치
        text = csv_path.read_text(encoding="utf-8-sig").replace("\nGLW,", "\nGLWX,", 1)
        csv_path.write_text(text, encoding="utf-8-sig")
    else:
        text = csv_path.read_text(encoding="utf-8-sig").replace(",통신·미디어,신호전송", ",없는L1,신호전송", 1)
        csv_path.write_text(text, encoding="utf-8-sig")
    out = tmp_path / "generated"
    r = run("--source", str(src), "--out", str(out))
    assert r.returncode == 1 and "아무것도 쓰지 않았다" in r.stderr
    assert not out.exists()


def test_leftover_tmp_is_cleaned_and_ignored_by_loader(tmp_path):
    d = tmp_path / "vc"
    out = d / "generated"
    out.mkdir(parents=True)
    shutil.copy(vc.VALUECHAIN_DIR / "core.ttl", d / "core.ttl")
    (out / ".tx-energy.ttl.tmp").write_text("쓰는 중 — 깨진 turtle", encoding="utf-8")
    (out / ".hidden.ttl").write_text("점 파일도 읽지 않는다", encoding="utf-8")
    sectors, errors = vc.load_all(d)
    assert sectors == [] and errors == []                 # 점 접두 파일은 로더가 보지 않는다
    assert run("--source", str(SRC), "--out", str(out)).returncode == 0
    assert not (out / ".tx-energy.ttl.tmp").exists()      # 시작 시 정리


def test_generated_with_bio_is_valid(tmp_path):
    """생성물 + core + bio 복사본 → validate 통과. TEM·GOOGL 은 bio 와 IRI 를 공유하되 라벨이 달라도 된다."""
    shutil.copy(vc.VALUECHAIN_DIR / "core.ttl", tmp_path / "core.ttl")
    shutil.copy(vc.VALUECHAIN_DIR / "bio.ttl", tmp_path / "bio.ttl")
    shutil.copytree(EXPECTED, tmp_path / "generated")
    assert vc.validate(tmp_path) == []
    sectors, _ = vc.load_all(tmp_path)
    assert [s.code for s in sectors] == ["bio", "tx-communications", "tx-financials", "tx-healthcare",
                                         "tx-industrials"]
    by = {s.code: s for s in sectors}
    assert by["bio"].kind == "theme" and by["tx-healthcare"].kind == "taxonomy"
    assert by["tx-healthcare"].file == "generated/tx-healthcare.ttl"
    tx_tem, bio_tem = by["tx-healthcare"].companies["US-TEM"], by["bio"].companies["US-TEM"]
    assert tx_tem.name == "Tempus AI Inc." and bio_tem.name == "Tempus AI"        # 파일별 관점
    assert tx_tem.isin == "US88023B1035" and bio_tem.isin is None
    jpm = next(m for m in by["tx-financials"].memberships if m.company == "US-JPM")
    assert jpm.role == "소매은행" and jpm.url == "https://jpmorganchase.com/ir"
    assert jpm.points == ['근거 "따옴표"와 백슬래시 \\ 포함.\n둘째 줄.']           # 이스케이프 왕복
    ind = by["tx-industrials"]
    assert [c.code for c in ind.roots()] == ["I02", "I00"]                        # 미확정은 맨 뒤
    assert ind.categories["I00"].short == "L2 미확정"
    assert {m.company for m in ind.memberships} == {"US-BA", "US-MOG.A", "US-HON"}  # HON 중복 제거
    comm = by["tx-communications"]
    assert comm.companies["US-PPLI"].name == "People Incorporated"                # current_name
    assert {"US-GOOGL", "US-GOOG"} <= comm.companies.keys()                       # 티커별 2장


SHARED = """\
@prefix vc:   <http://ge.local/valuechain#> .
@prefix co:   <http://ge.local/company#> .
@prefix {p}:  <http://ge.local/valuechain/{p}#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

{p}:S a vc:Sector ; vc:code "{p}" ; vc:kind "{kind}" ; rdfs:label "{p}"@ko .
{p}:A a vc:Category ; vc:subCategoryOf {p}:S ; vc:code "A" ; vc:order 1 ; rdfs:label "A"@ko .
co:{iri} a vc:Company ; rdfs:label "{label}" ; vc:ticker "{ticker}" ; vc:country "US" ; vc:listed true .
{p}:m a vc:Membership ; vc:company co:{iri} ; vc:sector {p}:S ; vc:primaryCategory {p}:A ; vc:belongsTo {p}:A .
"""


def _pair(tmp_path, a: dict, b: dict) -> list[str]:
    shutil.copy(vc.VALUECHAIN_DIR / "core.ttl", tmp_path / "core.ttl")
    (tmp_path / "aa.ttl").write_text(SHARED.format(p="aa", kind="theme", **a), encoding="utf-8")
    (tmp_path / "bb.ttl").write_text(SHARED.format(p="bb", kind="theme", **b), encoding="utf-8")
    return vc.validate(tmp_path)


def test_cross_file_same_iri_needs_same_ticker(tmp_path):
    problems = _pair(tmp_path, dict(iri="US-BRK.B", ticker="BRK.B", label="Berkshire"),
                     dict(iri="US-BRK.B", ticker="BRK-B", label="버크셔"))
    assert len(problems) == 1 and "US-BRK.B" in problems[0] and "같아야 한다" in problems[0]


def test_cross_file_same_ticker_needs_one_iri(tmp_path):
    problems = _pair(tmp_path, dict(iri="US-BRK.B", ticker="BRK.B", label="Berkshire"),
                     dict(iri="US-BRK-B", ticker="BRK.B", label="Berkshire"))
    assert len(problems) == 1 and "IRI 가 하나여야 한다" in problems[0]


def test_cross_file_label_difference_is_fine(tmp_path):
    assert _pair(tmp_path, dict(iri="US-TEM", ticker="TEM", label="Tempus AI"),
                 dict(iri="US-TEM", ticker="TEM", label="Tempus AI Inc.")) == []


def test_bad_kind_is_reported(tmp_path):
    shutil.copy(vc.VALUECHAIN_DIR / "core.ttl", tmp_path / "core.ttl")
    (tmp_path / "aa.ttl").write_text(
        SHARED.format(p="aa", kind="other", iri="US-X", ticker="X", label="X"), encoding="utf-8")
    assert any("vc:kind" in p for p in vc.validate(tmp_path))


def test_parse_registry_anchors_to_l1_sections():
    reg = it.parse_registry((SRC / "work" / "taxonomy_registry.md").read_text(encoding="utf-8"))
    assert list(reg) == list(it.L1_META)                                  # 12개, 레지스트리 순
    assert [lab for lab, _ in reg["금융"]] == ["예금·대출 은행", "보험 위험인수"]   # 경계 절 줄 무시
    assert dict(reg["산업재·건설"])["항공우주·방산제조"] == "장비 제조·방위 계약."  # 신설 비고 제거
    assert all("범위 밖" not in lab for v in reg.values() for lab, _ in v)


@pytest.mark.parametrize("raw,want", [
    ("BRK/A", "BRK.A"), ("BRK/B", "BRK.B"), ("MOGa", "MOG.A"), ("LENb", "LEN.B"), ("GOOGL", "GOOGL"),
])
def test_normalize_ticker(raw, want):
    assert it.normalize_ticker(raw) == want


def test_normalize_ticker_rejects_unsafe():
    with pytest.raises(ValueError):
        it.normalize_ticker("AB C")


@pytest.mark.parametrize("raw,want", [
    ("Corning Incorporated Common Stock", "Corning Incorporated"),
    ("Alphabet Inc. Class C Capital Stock", "Alphabet Inc."),
    ("Boeing Company (The) Common Stock", "The Boeing Company"),
    ("Anheuser-Busch Inbev SA Sponsored ADR (Belgium)", "Anheuser-Busch Inbev SA"),
    ("ZTO Express (Cayman) Inc. American Depositary Shares each representing one Class A ordinary share.",
     "ZTO Express (Cayman) Inc."),
    ("Iron Mountain Incorporated (Delaware)Common Stock REIT", "Iron Mountain Incorporated"),
    ("RLJ Lodging Trust Common Shares of Beneficial Interest $0.01 par value", "RLJ Lodging Trust"),
    ("Plains GP Holdings L.P. Class A Units representing Limited Partner Interests", "Plains GP Holdings L.P."),
    ("HEICO CORP-CLASS A", "HEICO CORP"),
    ("Berkshire Hathaway Inc.", "Berkshire Hathaway Inc."),
    ("Common Stock", "Common Stock"),                     # 빈 결과면 원문
])
def test_clean_name(raw, want):
    assert it.clean_name(raw) == want
