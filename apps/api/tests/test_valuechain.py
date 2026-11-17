"""산업 밸류체인(계획 S7) — storage/valuechain/*.ttl 로더 · 검증 · API.

지키려는 것:
  - 실제 정본(bio.ttl)이 검증을 통과하고 숫자가 원본과 맞는다.
  - **새 섹터는 파일만 추가하면 나타난다**(코드 수정 0, 계획 §12-11 — tmp 디렉터리에서만).
  - 보유·관심 표시가 DB 와 맞는다.
"""
import shutil
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.valuechain import router
from app.core import valuechain as vc
from app.core.errors import register_exception_handlers
from app.db.session import get_db
from app.models import Account, Asset, Broker, BrokerageConnection, CurrentPosition

EXAMPLE_TTL = """\
@prefix vc:   <http://ge.local/valuechain#> .
@prefix co:   <http://ge.local/company#> .
@prefix ex:   <http://ge.local/valuechain/example#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Ex a vc:Sector ; vc:code "example" ; rdfs:label "예시"@ko .

ex:A a vc:Category ; vc:subCategoryOf ex:Ex ; vc:code "A" ; vc:order 1 ;
    vc:color "#111111" ; rdfs:label "상류"@ko .
ex:A-1 a vc:Category ; vc:subCategoryOf ex:A ; vc:code "A-1" ; vc:order 1 ; rdfs:label "상류-1"@ko .
ex:A vc:feedsInto ex:A-1 .

co:US-NVDA a vc:Company ; rdfs:label "NVIDIA"@ko ; vc:ticker "NVDA" ; vc:exchange "US" ;
    vc:country "US" ; vc:listed true .
ex:m-US-NVDA a vc:Membership ; vc:company co:US-NVDA ; vc:sector ex:Ex ;
    vc:primaryCategory ex:A ; vc:belongsTo ex:A , ex:A-1 ; vc:role "GPU" ; vc:points ( "하나" "둘" ) .

co:KR-x-sample a vc:Company ; rdfs:label "샘플"@ko ; vc:country "KR" ; vc:listed false .
ex:m-KR-x-sample a vc:Membership ; vc:company co:KR-x-sample ; vc:sector ex:Ex ;
    vc:primaryCategory ex:A-1 ; vc:belongsTo ex:A-1 .
"""


@pytest.fixture
def two_sectors(tmp_path):
    """정본 core.ttl·bio.ttl 복사 + 작은 예시 섹터. 저장소 파일은 건드리지 않는다."""
    for name in ("core.ttl", "bio.ttl"):
        shutil.copy(vc.VALUECHAIN_DIR / name, tmp_path / name)
    (tmp_path / "_example.ttl").write_text(EXAMPLE_TTL, encoding="utf-8")
    return tmp_path


# 분류 생성물(storage/valuechain/generated/) L1별 멤버십 수 — 원천 2026-09-28 08:32 기준(필수 101→102), HON 중복 제거(산업재 368→367).
# ⚠️원천을 갱신해 import_taxonomy.py 를 다시 돌리면 이 숫자도 함께 고친다(테스트는 원천 폴더를 읽지 않는다).
TX_MEMBERS = {
    "tx-financials": 420, "tx-industrials": 367, "tx-healthcare": 321, "tx-discretionary": 227,
    "tx-digital": 214, "tx-materials": 173, "tx-energy": 150, "tx-realestate": 132,
    "tx-communications": 131, "tx-bizservices": 107, "tx-staples": 102, "tx-utilities": 75,
}


def test_real_storage_is_valid():
    assert vc.validate() == []
    sectors, errors = vc.load_all()
    assert errors == [] and [s.code for s in sectors] == ["bio"] + sorted(TX_MEMBERS)
    tx = {s.code: s for s in sectors if s.kind == "taxonomy"}
    assert {c: len(s.memberships) for c, s in tx.items()} == TX_MEMBERS
    assert sum(TX_MEMBERS.values()) == 2419
    assert all(s.file == f"generated/{s.code}.ttl" and not s.flows for s in tx.values())
    assert all(m.primary and m.categories == [m.primary] for s in tx.values() for m in s.memberships)
    assert max(len(s.roots()) for s in tx.values()) == 20                    # 산업재 19 + L2 미확정
    assert len(tx["tx-financials"].categories["F01"].contains) == 171         # 예금·대출 은행
    brk = tx["tx-financials"].companies["US-BRK.B"]                           # 클래스주 점 표기
    assert brk.ticker == "BRK.B" and brk.isin
    bio = sectors[0]
    assert bio.kind == "theme"
    assert [c.code for c in bio.roots()] == ["A", "B-1", "B-2", "B-3", "C"]
    assert len(bio.categories) == 22
    # 원본 125행 → 결합 행 분리 후 140(변환 리포트). 크게 어긋나면 변환이 틀린 것.
    assert 125 <= len(bio.memberships) == len(bio.companies) <= 160
    assert all(m.primary and m.categories[0] == m.primary for m in bio.memberships)
    assert ("A", "B-1") in bio.flows and ("C-1", "C-2") in bio.flows
    ilmn = next(m for m in bio.memberships if m.company == "US-ILMN")
    assert ilmn.categories == ["A-4", "A-1"] and len(ilmn.points) == 4        # rdf:List 순서 보존
    for ticker in ("468530", "287840"):
        company = bio.companies[f"KR-{ticker}"]
        assert company.listed is True
        assert company.ticker == ticker and company.exchange == "KRX"
    assert bio.categories["A-1"].color == bio.categories["A"].color          # 색 상속


def test_new_sector_appears_without_code_change(two_sectors):
    assert vc.validate(two_sectors) == []
    sectors, _ = vc.load_all(two_sectors)
    assert [s.code for s in sectors] == ["example", "bio"]                  # 파일 이름 순
    ex = sectors[0]
    assert ex.categories["A"].children == ["A-1"]                            # 유도: hasSubCategory
    assert sorted(ex.categories["A-1"].contains) == ["KR-x-sample", "US-NVDA"]  # 유도: contains
    assert ex.categories["A-1"].color == "#111111"
    nvda = next(m for m in ex.memberships if m.company == "US-NVDA")
    assert nvda.points == ["하나", "둘"] and nvda.categories == ["A", "A-1"]


def test_validate_reports_broken_file(tmp_path):
    shutil.copy(vc.VALUECHAIN_DIR / "core.ttl", tmp_path / "core.ttl")
    broken = EXAMPLE_TTL.replace("vc:primaryCategory ex:A ;", "vc:primaryCategory ex:Nope ;") \
        .replace("ex:A vc:feedsInto ex:A-1 .", "ex:A vc:feedsInto ex:Ghost .")
    (tmp_path / "broken.ttl").write_text(broken, encoding="utf-8")
    (tmp_path / "junk.ttl").write_text("this is not turtle", encoding="utf-8")
    problems = vc.validate(tmp_path)
    assert any("primaryCategory" in p for p in problems)
    assert any("feedsInto" in p and "Ghost" in p for p in problems)
    assert any(p.startswith("junk.ttl: 파싱 실패") for p in problems)


@pytest.fixture
def api(db):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c


def _hold(db, ticker: str) -> None:
    broker_id, conn_id, acc_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db.add(Broker(id=broker_id, code="KIWOOM", name="키움증권"))
    db.flush()
    db.add(BrokerageConnection(id=conn_id, broker_id=broker_id, connection_name="주계좌",
                               environment="REAL", status="CONNECTED"))
    db.flush()
    db.add(Account(id=acc_id, broker_id=broker_id, brokerage_connection_id=conn_id,
                   external_account_id="0000", account_number_masked="0000-**",
                   account_name="시험 계좌", base_currency="KRW", is_active=True))
    db.add(Asset(id=asset_id, country="US", market="US", ticker=ticker, name=ticker,
                 asset_type="STOCK", currency="USD"))
    db.flush()
    db.add(CurrentPosition(id=uuid.uuid4(), account_id=acc_id, asset_id=asset_id, quantity=Decimal("3"),
                           as_of=datetime(2026, 9, 27, tzinfo=timezone.utc)))
    db.commit()


def test_api_sector_tree_and_flags(api, db):
    _hold(db, "GOOGL")
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'TEM')"), {"i": uuid.uuid4()})
    db.commit()

    lst = api.get("/api/v1/research/valuechain/sectors").json()
    assert lst[0] == {"code": "bio", "name": "바이오", "en": "Bio", "kind": "theme", "color": None, "categories": 22,
                      "companies": len(vc.get_sector("bio").memberships), "problems": 0}
    assert {s["code"]: (s["kind"], s["companies"]) for s in lst[1:]} == {c: ("taxonomy", n) for c, n in TX_MEMBERS.items()}

    d = api.get("/api/v1/research/valuechain/bio").json()
    assert [c["id"] for c in d["categories"]] == ["A", "B-1", "B-2", "B-3", "C"]
    a = d["categories"][0]
    assert [c["id"] for c in a["children"]] == ["A-1", "A-2", "A-3", "A-4"] and a["color"] == "#23865f"
    assert "US-TEM" in a["children"][0]["companies"]
    # 모든 기업이 트리 어딘가에 정확히 한 번(주 소속) 놓인다.
    placed = []

    def walk(n):
        placed.extend(n["companies"])
        for ch in n["children"]:
            walk(ch)
    for c in d["categories"]:
        walk(c)
    assert sorted(placed) == sorted(d["companies"])
    tem = d["companies"]["US-TEM"]
    assert tem["watch"] is True and tem["held"] is False
    assert tem["categories"] == ["A-1", "B-2-2"] and tem["primary"] == "A-1"
    assert tem["name"] == "Tempus AI" and tem["en"] is None and tem["url"] is None   # en == name → None
    assert d["companies"]["US-GOOGL"]["held"] is True
    assert d["flows"][0] == ["A", "B-1"] and len(d["theses"]) == 6 and len(d["sources"]) == 10
    assert api.get("/api/v1/research/valuechain/nope").status_code == 404


def test_api_lists_new_sector(api, two_sectors, monkeypatch):
    monkeypatch.setattr(vc, "VALUECHAIN_DIR", two_sectors)
    codes = [s["code"] for s in api.get("/api/v1/research/valuechain/sectors").json()]
    assert codes == ["example", "bio"]
    d = api.get("/api/v1/research/valuechain/example").json()
    assert d["categories"][0]["children"][0]["companies"] == ["KR-x-sample"]
    assert d["companies"]["KR-x-sample"]["listed"] is False


def test_real_catalog_is_valid():
    groups, entries, problems = vc.load_catalog()
    assert problems == [] and groups and any(e.code == "bio" for e in entries)


def test_api_catalog_marks_built_and_unlisted(api, two_sectors, monkeypatch):
    """카탈로그 카드는 섹터 파일이 있을 때만 열리고, 카탈로그에 없는 섹터 파일은 '미분류'로 보인다."""
    shutil.copy(vc.VALUECHAIN_DIR / "catalog.ttl", two_sectors / "catalog.ttl")
    monkeypatch.setattr(vc, "VALUECHAIN_DIR", two_sectors)
    assert vc.validate(two_sectors) == []
    groups = api.get("/api/v1/research/valuechain/catalog").json()
    cards = {c["code"]: c for g in groups for c in g["sectors"]}
    assert cards["bio"]["built"] is True and cards["bio"]["companies"] >= 125
    assert cards["semi"]["built"] is False and cards["semi"]["companies"] == 0
    assert groups[-1]["name"] == "미분류" and [c["code"] for c in groups[-1]["sectors"]] == ["example"]
    # 카탈로그 파일은 섹터로 읽히지 않는다.
    assert [s["code"] for s in api.get("/api/v1/research/valuechain/sectors").json()] == ["example", "bio"]


def test_real_catalog_groups_are_l1(api):
    """허브 = 분류 L1 12 묶음(레지스트리 순), 묶음마다 첫 카드가 분류 섹터. 기존 테마 카드 12장은 보존."""
    groups = api.get("/api/v1/research/valuechain/catalog").json()
    assert [g["name"] for g in groups] == ["산업재·건설", "금융", "재량소비", "헬스케어", "자원·기초소재",
                                          "디지털·컴퓨팅", "통신·미디어", "에너지", "필수·반복소비", "부동산",
                                          "공공유틸리티", "기업서비스"]
    for g in groups:
        first = g["sectors"][0]
        assert first["kind"] == "taxonomy" and first["built"] and first["code"].startswith("tx-")
        assert first["companies"] == TX_MEMBERS[first["code"]]
    where = {c["code"]: g["name"] for g in groups for c in g["sectors"]}
    themes = {"semi", "software", "bio", "media", "consumer", "ev", "staples", "energy", "power",
              "industrials", "materials", "financials"}
    assert themes <= where.keys()
    assert where["bio"] == "헬스케어" and where["power"] == "산업재·건설"
    cards = {c["code"]: c for g in groups for c in g["sectors"]}
    assert cards["bio"]["built"] and cards["bio"]["kind"] == "theme"
    assert not cards["semi"]["built"] and cards["semi"]["kind"] == "theme"


def test_api_taxonomy_sector(api, db):
    """분류 섹터 응답 — 모든 기업이 트리에 정확히 1번, 근거 링크, en 중복 제거, 역할(L3) 원문."""
    _hold(db, "JPM")
    d = api.get("/api/v1/research/valuechain/tx-financials").json()
    assert d["flows"] == [] and len(d["companies"]) == 420
    assert [c["id"] for c in d["categories"]][-1] == "F00"                   # L2 미확정은 맨 뒤
    placed = []

    def walk(n):
        placed.extend(n["companies"])
        for ch in n["children"]:
            walk(ch)
    for c in d["categories"]:
        walk(c)
    assert sorted(placed) == sorted(d["companies"]) and len(placed) == len(set(placed))
    assert all(co["url"] and co["url"].startswith("http") for co in d["companies"].values())
    assert all(co["en"] is None for co in d["companies"].values())            # 무태그 라벨 = name
    jpm = d["companies"]["US-JPM"]
    assert jpm["held"] is True and jpm["primary"] == "F01" and jpm["src"] == ["분류체계"]
    assert jpm["points"] and jpm["role"]


def test_load_all_perf_guard():
    """13 섹터(≈2.5k 기업) 콜드 로드 < 5s, mtime 캐시 웜 로드 < 50ms.

    ★2026-11-16 사용자 결정: 콜드 한도 2s → 5s. 배터리·부하에서 2.0~4.1s 로 흔들려 훅을 막았다
    (실측). 급격한 저하(수십 초)는 여전히 잡는다."""
    vc._cache.clear()
    t = time.perf_counter()
    vc.load_all()
    cold = time.perf_counter() - t
    t = time.perf_counter()
    vc.load_all()
    warm = time.perf_counter() - t
    assert cold < 5.0, cold
    assert warm < 0.05, warm


def test_taxonomy_colors_follow_l1(api):
    """분류 섹터는 L1 기준색 하나 — 섹터·모든 L2(미확정 제외)·허브 묶음이 같은 색이다."""
    for s in vc.load_all()[0]:
        if s.kind != "taxonomy":
            continue
        assert s.color and s.color.startswith("#")
        assert {c.color for c in s.categories.values() if not c.code.endswith("00")} == {s.color}
    groups = api.get("/api/v1/research/valuechain/catalog").json()
    for g in groups:
        tx = next(c for c in g["sectors"] if c["kind"] == "taxonomy")
        assert g["color"] == tx["color"]
    assert len({g["color"] for g in groups}) == 12                       # L1 마다 다른 색
