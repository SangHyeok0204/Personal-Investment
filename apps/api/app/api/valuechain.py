"""산업 밸류체인 API (계획 §5.2) — `/research/valuechain` 화면이 쓴다.

데이터는 `storage/valuechain/*.ttl`(사람이 고치는 정본)에서 온다 — DB 가 아니다.
DB 는 보유(held)·관심(watch) 표시에만 쓴다.

응답은 원본 bio_data.json 과 같은 모양이되 분류가 **트리**다: 파일에는 subCategoryOf·belongsTo
한 방향만 있고, 여기서는 그 역(children = composedOf, companies = contains)으로 내려준다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import valuechain as vc
from app.core.errors import AppError
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/research/valuechain", tags=["valuechain"])


class SectorSummary(BaseModel):
    code: str
    name: str
    en: str | None
    kind: str                            # "theme"(손 편집 테마) | "taxonomy"(generated/ 분류 생성물)
    color: str | None = None             # 섹터 기준색(분류 섹터 = L1 기준색)
    categories: int
    companies: int
    problems: int


class SectorInfo(BaseModel):
    code: str
    name: str
    en: str | None
    desc: str | None
    color: str | None = None
    problems: list[str]


class CategoryNode(BaseModel):
    id: str
    code: str
    name: str
    short: str | None
    desc: str | None
    color: str | None
    order: int
    market: str | None
    children: list[CategoryNode]
    companies: list[str]                 # 이 분류가 주 소속인 기업 id


class CompanyOut(BaseModel):
    name: str
    en: str | None                       # ★name 과 같으면 None(무태그 라벨 중복 — 응답 크기 절약)
    ticker: str | None
    exchange: str | None
    country: str | None
    other_countries: list[str]
    listed: bool
    role: str | None
    points: list[str]
    categories: list[str]                # 주 소속이 먼저
    primary: str | None
    src: list[str]
    url: str | None = None               # 판정 근거 링크(vc:url, 분류 생성물)
    held: bool
    watch: bool


class Thesis(BaseModel):
    src: str | None
    text: str | None


class Source(BaseModel):
    tag: str
    file: str | None
    note: str | None


class SectorDetail(BaseModel):
    sector: SectorInfo
    categories: list[CategoryNode]
    flows: list[tuple[str, str]]
    companies: dict[str, CompanyOut]
    theses: list[Thesis]
    sources: list[Source]


@router.get("/sectors", response_model=list[SectorSummary])
def list_sectors():
    sectors, _ = vc.load_all()
    return [
        SectorSummary(code=s.code, name=s.name, en=s.name_en, kind=s.kind, color=s.color, categories=len(s.categories),
                      companies=len(s.memberships), problems=len(s.problems))
        for s in sectors
    ]


class CatalogCard(BaseModel):
    code: str
    name: str
    en: str | None
    desc: str | None
    kind: str                            # 섹터 파일의 vc:kind. 미작성 카드는 "theme"
    color: str | None = None             # 섹터 기준색. 없으면 화면이 묶음 색을 쓴다
    built: bool                          # 섹터 파일이 있어 들어갈 수 있는가
    categories: int
    companies: int
    mine: int                            # 보유·관심 기업 수
    problems: int


class CatalogGroupOut(BaseModel):
    id: str
    name: str
    color: str | None = None             # 묶음(L1) 기준색 — 묶음 안 분류 섹터의 색
    sectors: list[CatalogCard]


@router.get("/catalog", response_model=list[CatalogGroupOut])
def get_catalog(db: Session = Depends(get_db)):
    """섹터 허브 — catalog.ttl 의 묶음·카드에 섹터 파일 통계를 붙인다.

    ★카탈로그에 없는 섹터 파일은 맨 뒤 "미분류" 묶음으로 보인다(숨기지 않는다).
    ⚠️`/{sector}` 보다 **먼저** 선언해야 한다 — 아니면 "catalog" 가 섹터 코드로 잡힌다.
    """
    sectors, _ = vc.load_all()
    groups, entries, _ = vc.load_catalog()
    by_code = {s.code: s for s in sectors}
    held, watch = _held_watch(db)
    held_t = {t for t, _ in held}

    def card(code: str, name: str, en: str | None, desc: str | None) -> CatalogCard:
        s = by_code.get(code)
        if s is None:
            return CatalogCard(code=code, name=name, en=en, desc=desc, kind="theme", built=False,
                               categories=0, companies=0, mine=0, problems=0)
        mine = sum(
            1 for m in s.memberships
            if (t := (s.companies[m.company].ticker or "").upper()) and (t in held_t or t in watch)
        )
        return CatalogCard(code=code, name=s.name or name, en=s.name_en or en, desc=desc or s.desc,
                           kind=s.kind, color=s.color, built=True, categories=len(s.categories), companies=len(s.memberships),
                           mine=mine, problems=len(s.problems))

    def group(gid: str, name: str, cards: list[CatalogCard]) -> CatalogGroupOut:
        # 묶음 색 = 분류 섹터(L1)의 기준색. 색이 따로 적히지 않아 한 곳(생성기)에서만 정해진다.
        color = next((c.color for c in cards if c.kind == "taxonomy" and c.color), None)
        return CatalogGroupOut(id=gid, name=name, color=color, sectors=cards)

    out = [
        group(g.id, g.name, [
            card(e.code, e.name, e.name_en, e.desc)
            for e in sorted((e for e in entries if e.group == g.id), key=lambda e: e.order)
        ])
        for g in groups
    ]
    listed = {e.code for e in entries}
    loose = [e for e in entries if e.group is None]
    extra = [card(e.code, e.name, e.name_en, e.desc) for e in sorted(loose, key=lambda e: e.order)]
    extra += [card(s.code, s.name, s.name_en, s.desc) for s in sectors if s.code not in listed]
    if extra:
        out.append(group("_unlisted", "미분류", extra))
    return [g for g in out if g.sectors]


def _held_watch(db: Session) -> tuple[set[tuple[str, str]], set[str]]:
    """보유 (티커, 국가) · 관심 티커. 관심종목 표에는 국가가 없어 티커로만 맞춘다."""
    held = {(t, c) for t, c in db.execute(text(
        "SELECT DISTINCT upper(a.ticker), a.country FROM current_positions p "
        "JOIN assets a ON a.id = p.asset_id WHERE p.quantity > 0")).all()}
    watch = set(db.execute(text("SELECT upper(ticker) FROM watchlist_items")).scalars())
    return held, watch


@router.get("/{sector}", response_model=SectorDetail)
def get_sector(sector: str, db: Session = Depends(get_db)):
    s = vc.get_sector(sector)
    if s is None:
        raise AppError(404, "NOT_FOUND", f"섹터 {sector} 가 없습니다")
    held, watch = _held_watch(db)
    primary_of = {m.company: m.primary for m in s.memberships}

    def node(c: vc.Category) -> CategoryNode:
        return CategoryNode(
            id=c.code, code=c.code, name=c.name, short=c.short, desc=c.desc, color=c.color,
            order=c.order, market=c.market, children=[node(s.categories[k]) for k in c.children],
            companies=[cid for cid in c.contains if primary_of.get(cid) == c.code],
        )

    companies = {}
    for m in s.memberships:
        co = s.companies[m.company]
        t = (co.ticker or "").upper()
        companies[co.id] = CompanyOut(
            name=co.name, en=co.en if co.en != co.name else None, ticker=co.ticker, exchange=co.exchange, country=co.country,
            other_countries=co.other_countries, listed=co.listed, role=m.role, points=m.points,
            categories=m.categories, primary=m.primary, src=m.sources, url=m.url,
            held=bool(t) and (t, co.country) in held, watch=bool(t) and t in watch,
        )
    return SectorDetail(
        sector=SectorInfo(code=s.code, name=s.name, en=s.name_en, desc=s.desc, color=s.color, problems=s.problems),
        categories=[node(c) for c in s.roots()],
        flows=s.flows,
        companies=companies,
        theses=s.theses,
        sources=s.sources,
    )
