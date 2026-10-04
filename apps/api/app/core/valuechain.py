"""산업 밸류체인 로더 (계획 §5, §12-5·6) — `storage/valuechain/*.ttl` → dataclass.

섹터 불문이다: `core.ttl` 은 스키마, **나머지 *.ttl 하나 = 섹터 하나**. 새 섹터는 파일만
추가하면 된다(코드 수정 0, `storage/valuechain/README.md`).
★두 곳을 읽는다: 최상위 `*.ttl`(손으로 쓰는 테마, 정본) + `generated/*.ttl`(import_taxonomy.py 가
  덮어쓰는 분류 생성물). 점으로 시작하는 파일(원자적 쓰기의 `.tx-….ttl.tmp`)은 읽지 않는다.

★파일에는 한 방향만 있다(subCategoryOf·belongsTo). 역방향(children = hasSubCategory/
  composedOf, contains)은 여기서 만든다.
★SPARQL 을 안 쓴다 — 이웃 조회뿐이라 `graph.objects()` 직접 순회로 충분하다(구 market_signal
  graph.py 와 같은 판단).
★mtime 캐시: 파일이 바뀌면 다음 요청에서 그 파일만 다시 읽는다. 사람이 ttl 을 고치고
  새로고침하면 바로 보인다(재시작 불필요).
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, Namespace
from rdflib.collection import Collection

VC = Namespace("http://ge.local/valuechain#")

# 설정값(계획 §12-6). config.py 를 건드리지 않으려고 환경변수를 직접 읽는다.
VALUECHAIN_DIR = Path(
    os.environ.get("VALUECHAIN_DIR") or Path(__file__).resolve().parents[4] / "storage" / "valuechain"
)
SCHEMA_FILE = "core.ttl"
CATALOG_FILE = "catalog.ttl"   # 섹터 허브 목록 — 섹터 파일이 아니다
GENERATED_DIR = "generated"    # 자동 생성 분류 섹터(scripts/valuechain/import_taxonomy.py) — 손 편집 금지
SECTOR_KINDS = ("theme", "taxonomy")


@dataclass
class Category:
    code: str
    name: str
    short: str | None
    desc: str | None
    color: str | None
    order: int
    market: str | None
    parent: str | None                   # 상위 분류 코드. 최상위면 None
    children: list[str] = field(default_factory=list)     # 유도: hasSubCategory
    contains: list[str] = field(default_factory=list)     # 유도: 소속 기업 id(주·부 소속 모두)
    feeds_into: list[str] = field(default_factory=list)


@dataclass
class Company:
    id: str                              # co: 로컬명(KR-196170, US-x-benchling)
    name: str
    en: str | None
    ticker: str | None
    exchange: str | None
    country: str | None
    other_countries: list[str]
    listed: bool
    isin: str | None = None              # 선택(vc:isin) — 분류 생성물이 기록한다


@dataclass
class Membership:
    company: str                         # Company.id
    categories: list[str]                # 주 소속이 먼저, 나머지는 트리 순서
    primary: str | None
    role: str | None
    points: list[str]
    sources: list[str]                   # Source.tag
    url: str | None = None               # 선택(vc:url) — 판정 근거 링크


@dataclass
class Sector:
    code: str
    name: str
    name_en: str | None
    desc: str | None
    file: str
    categories: dict[str, Category]      # 코드 → 분류, 트리 순서(깊이 우선)
    companies: dict[str, Company]
    memberships: list[Membership]
    flows: list[tuple[str, str]]
    theses: list[dict]
    sources: list[dict]
    problems: list[str]
    kind: str = "theme"                  # vc:kind — "theme"(손 편집) | "taxonomy"(생성물)
    color: str | None = None             # vc:color(선택) — 허브 덱·카드 기준색

    def roots(self) -> list[Category]:
        return [c for c in self.categories.values() if c.parent is None]


def _text(g: rdflib.Graph, s, p, lang: str | None = None) -> str | None:
    """p 의 리터럴 하나. lang 을 주면 그 언어 → 언어 없는 것 순으로 고른다."""
    vals = [o for o in g.objects(s, p) if isinstance(o, rdflib.Literal)]
    if lang:
        for want in (lang, None):
            for o in vals:
                if o.language == want:
                    return str(o)
        return None
    return str(vals[0]) if vals else None


def _int(g, s, p, default: int = 0) -> int:
    v = g.value(s, p)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


def _local(iri) -> str:
    s = str(iri)
    return s.rsplit("#", 1)[-1] if "#" in s else s.rsplit("/", 1)[-1]


def parse_sector(path: Path, base_dir: Path | None = None) -> Sector:
    """섹터 파일 하나 → Sector. 구조 문제는 `problems` 에 모은다(예외로 죽지 않는다).

    `Sector.file` 은 base_dir 기준 상대 경로(generated/tx-….ttl 처럼 하위 디렉터리를 구분)."""
    g = rdflib.Graph()
    with open(path, "rb") as f:          # ★경로 문자열을 넘기면 rdflib 가 URL 로 오해한다
        g.parse(source=f, format="turtle")
    problems: list[str] = []
    where = path.relative_to(base_dir).as_posix() if base_dir else path.name

    sectors = list(g.subjects(RDF.type, VC.Sector))
    if len(sectors) != 1:
        raise ValueError(f"{where}: vc:Sector 가 정확히 1개여야 한다(현재 {len(sectors)})")
    sec = sectors[0]
    code = _text(g, sec, VC.code) or path.stem
    kind = _text(g, sec, VC.kind) or "theme"
    if kind not in SECTOR_KINDS:
        problems.append(f"{where}: vc:kind {kind!r} 는 {'/'.join(SECTOR_KINDS)} 중 하나여야 한다")

    # ── 분류 ──
    cat_nodes = list(g.subjects(RDF.type, VC.Category))
    code_of = {}
    for n in cat_nodes:
        c = _text(g, n, VC.code) or _local(n)
        if c in code_of.values():
            problems.append(f"{where}: 분류 코드 중복 {c}")
        code_of[n] = c
    raw: dict[str, Category] = {}
    for n in cat_nodes:
        parents = list(g.objects(n, VC.subCategoryOf))
        c = code_of[n]
        parent = None
        if len(parents) != 1:
            problems.append(f"{where}: 분류 {c} 의 vc:subCategoryOf 가 {len(parents)}개(정확히 1개여야 함)")
        elif parents[0] != sec:
            if parents[0] in code_of:
                parent = code_of[parents[0]]
            else:
                problems.append(f"{where}: 분류 {c} 의 상위 {_local(parents[0])} 가 없다(고아 분류)")
        raw[c] = Category(
            code=c, name=_text(g, n, RDFS.label, "ko") or c, short=_text(g, n, VC.shortLabel),
            desc=_text(g, n, RDFS.comment, "ko"), color=_text(g, n, VC.color),
            order=_int(g, n, VC.order), market=_text(g, n, VC.marketSize), parent=parent,
        )
        for t in g.objects(n, VC.feedsInto):
            if t in code_of:
                raw[c].feeds_into.append(code_of[t])
            else:
                problems.append(f"{where}: {c} vc:feedsInto 대상 {_local(t)} 가 분류가 아니다")
    for cat in raw.values():                 # 유도: hasSubCategory
        if cat.parent:
            raw[cat.parent].children.append(cat.code)
    for cat in raw.values():
        cat.children.sort(key=lambda k: (raw[k].order, k))
        cat.feeds_into.sort(key=lambda k: (raw[k].order, k))

    # 순환이면 루트에 닿지 않는다 → 고아로 본다.
    categories: dict[str, Category] = {}

    def walk(k: str) -> None:
        categories[k] = raw[k]
        if raw[k].color is None and raw[k].parent:          # 색은 상위에서 물려받는다
            raw[k].color = raw[raw[k].parent].color
        for ch in raw[k].children:
            walk(ch)

    for root in sorted((c for c in raw.values() if c.parent is None), key=lambda c: (c.order, c.code)):
        walk(root.code)
    for k in raw.keys() - categories.keys():
        problems.append(f"{where}: 분류 {k} 가 섹터에 닿지 않는다(순환 또는 고아)")
    tree_pos = {k: i for i, k in enumerate(categories)}

    # ── 자료 ──
    src_nodes = sorted(g.subjects(RDF.type, VC.Source), key=lambda n: (_int(g, n, VC.order), str(n)))
    tag_of = {n: _text(g, n, VC.code) or _local(n) for n in src_nodes}
    sources = [{"tag": tag_of[n], "file": _text(g, n, RDFS.label, "ko"), "note": _text(g, n, RDFS.comment, "ko")}
               for n in src_nodes]
    theses = [{"src": _text(g, n, RDFS.label, "ko"), "text": _text(g, n, RDFS.comment, "ko")}
              for n in sorted(g.subjects(RDF.type, VC.Thesis), key=lambda n: (_int(g, n, VC.order), str(n)))]

    # ── 기업 · 멤버십 ──
    companies: dict[str, Company] = {}
    for n in g.subjects(RDF.type, VC.Company):
        cid = _local(n)
        listed = g.value(n, VC.listed)
        companies[cid] = Company(
            id=cid, name=_text(g, n, RDFS.label, "ko") or cid, en=_text(g, n, RDFS.label, "en"),
            ticker=_text(g, n, VC.ticker), exchange=_text(g, n, VC.exchange), country=_text(g, n, VC.country),
            other_countries=sorted(str(o) for o in g.objects(n, VC.otherCountry)),
            listed=bool(listed.toPython()) if listed is not None else bool(_text(g, n, VC.ticker)),
            isin=_text(g, n, VC.isin),
        )
    memberships: list[Membership] = []
    for m in g.subjects(RDF.type, VC.Membership):
        mid = _local(m)
        co = g.value(m, VC.company)
        cid = _local(co) if co is not None else None
        if cid not in companies:
            problems.append(f"{where}: 멤버십 {mid} 의 vc:company 가 vc:Company 가 아니다")
            continue
        cats = []
        for t in g.objects(m, VC.belongsTo):
            if t in code_of and code_of[t] in categories:
                cats.append(code_of[t])
            else:
                problems.append(f"{where}: {mid} vc:belongsTo 대상 {_local(t)} 가 분류가 아니다")
        if not cats:
            problems.append(f"{where}: {mid} 소속 분류(vc:belongsTo)가 없다")
        prim_node = g.value(m, VC.primaryCategory)
        primary = code_of.get(prim_node) if prim_node is not None else None
        if primary is None or primary not in cats:
            problems.append(f"{where}: {mid} vc:primaryCategory 가 vc:belongsTo 중 하나가 아니다")
            primary = None
        cats.sort(key=lambda k: (k != primary, tree_pos[k]))
        pts = g.value(m, VC.points)
        srcs = []
        for s in g.objects(m, VC.source):
            if s in tag_of:
                srcs.append(tag_of[s])
            else:
                problems.append(f"{where}: {mid} vc:source 대상 {_local(s)} 가 vc:Source 가 아니다")
        memberships.append(Membership(
            company=cid, categories=cats, primary=primary, role=_text(g, m, VC.role),
            points=[str(x) for x in Collection(g, pts)] if pts is not None else [],
            sources=sorted(srcs, key=lambda t: [s["tag"] for s in sources].index(t)),
            url=_text(g, m, VC.url),
        ))
        for k in cats:                           # 유도: contains
            categories[k].contains.append(cid)
    member_ids = {m.company for m in memberships}
    for cid in companies.keys() - member_ids:
        problems.append(f"{where}: 기업 {cid} 에 멤버십이 없다")
    memberships.sort(key=lambda m: (tree_pos.get(m.primary, 10**6), companies[m.company].name))

    flows = [(c.code, t) for c in categories.values() for t in c.feeds_into]
    return Sector(
        code=code, name=_text(g, sec, RDFS.label, "ko") or code, name_en=_text(g, sec, RDFS.label, "en"),
        desc=_text(g, sec, RDFS.comment, "ko"), file=where, categories=categories, companies=companies,
        memberships=memberships, flows=flows, theses=theses, sources=sources, problems=problems, kind=kind, color=_text(g, sec, VC.color),
    )


_lock = threading.Lock()
_cache: dict[Path, tuple[float, Sector | str]] = {}   # 파일 → (mtime, Sector 또는 파싱 오류)


def _load(path: Path, base_dir: Path) -> Sector | str:
    mtime = path.stat().st_mtime
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        val: Sector | str = parse_sector(path, base_dir)
    except Exception as e:  # noqa: BLE001 — 파일 하나가 깨져도 다른 섹터는 보여야 한다
        val = f"{path.relative_to(base_dir).as_posix()}: 파싱 실패 — {e}"
    _cache[path] = (mtime, val)
    return val


def load_all(directory: Path | None = None) -> tuple[list[Sector], list[str]]:
    """(섹터 목록, 파일 단위 오류). 섹터는 최상위 파일 이름 순 → generated/ 파일 이름 순."""
    d = Path(directory or VALUECHAIN_DIR)
    errors: list[str] = []
    sectors: list[Sector] = []
    with _lock:
        schema = d / SCHEMA_FILE
        if not schema.exists():
            errors.append(f"{SCHEMA_FILE} 가 없다: {schema}")
        else:
            try:
                with open(schema, "rb") as f:
                    rdflib.Graph().parse(source=f, format="turtle")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{SCHEMA_FILE}: 파싱 실패 — {e}")
        for p in sorted(d.glob("*.ttl")) + sorted((d / GENERATED_DIR).glob("*.ttl")):
            if p.parent == d and p.name in (SCHEMA_FILE, CATALOG_FILE):
                continue
            if p.name.startswith("."):       # ⚠️pathlib glob 은 점 파일도 잡는다 — 쓰는 중인 임시 파일 제외
                continue
            val = _load(p, d)
            if isinstance(val, str):
                errors.append(val)
            else:
                sectors.append(val)
    seen: dict[str, str] = {}
    for s in sectors:
        if s.code in seen:
            errors.append(f"섹터 코드 {s.code} 중복: {seen[s.code]}, {s.file}")
        seen.setdefault(s.code, s.file)
    return sectors, errors


def get_sector(code: str, directory: Path | None = None) -> Sector | None:
    sectors, _ = load_all(directory)
    return next((s for s in sectors if s.code == code), None)


@dataclass
class CatalogEntry:
    code: str
    name: str
    name_en: str | None
    desc: str | None
    group: str | None                    # SectorGroup 로컬명
    order: int


@dataclass
class CatalogGroup:
    id: str
    name: str
    order: int


def load_catalog(directory: Path | None = None) -> tuple[list[CatalogGroup], list[CatalogEntry], list[str]]:
    """catalog.ttl → (묶음, 카드, 문제). 파일이 없으면 빈 목록 — 허브는 섹터 파일만으로도 뜬다."""
    path = Path(directory or VALUECHAIN_DIR) / CATALOG_FILE
    if not path.exists():
        return [], [], []
    g = rdflib.Graph()
    try:
        with open(path, "rb") as f:
            g.parse(source=f, format="turtle")
    except Exception as e:  # noqa: BLE001
        return [], [], [f"{CATALOG_FILE}: 파싱 실패 — {e}"]
    problems: list[str] = []
    groups = {
        _local(n): CatalogGroup(id=_local(n), name=_text(g, n, RDFS.label, "ko") or _local(n),
                                order=_int(g, n, VC.order))
        for n in g.subjects(RDF.type, VC.SectorGroup)
    }
    for n in set(g.subjects(RDF.type, VC.SectorGroup)) & set(g.subjects(RDF.type, VC.SectorEntry)):
        problems.append(f"{CATALOG_FILE}: {_local(n)} 가 묶음이자 카드다 — IRI 를 나눌 것(속성이 섞인다)")
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for n in g.subjects(RDF.type, VC.SectorEntry):
        code = _text(g, n, VC.code)
        if not code:
            problems.append(f"{CATALOG_FILE}: {_local(n)} 에 vc:code 가 없다")
            continue
        if code in seen:
            problems.append(f"{CATALOG_FILE}: 섹터 코드 {code} 중복")
            continue
        seen.add(code)
        grp = g.value(n, VC.inGroup)
        gid = _local(grp) if grp is not None else None
        if gid is not None and gid not in groups:
            problems.append(f"{CATALOG_FILE}: {code} 의 묶음 {gid} 가 없다")
            gid = None
        entries.append(CatalogEntry(
            code=code, name=_text(g, n, RDFS.label, "ko") or code, name_en=_text(g, n, RDFS.label, "en"),
            desc=_text(g, n, RDFS.comment, "ko"), group=gid, order=_int(g, n, VC.order),
        ))
    return sorted(groups.values(), key=lambda x: x.order), entries, problems


def _cross_file_problems(sectors: list[Sector]) -> list[str]:
    """여러 섹터 파일이 공유하는 기업 신원 검사(라벨 차이는 문제 아님 — 파일별 관점).

    · 정방향: 같은 기업 IRI 는 모든 파일에서 vc:ticker·vc:country 가 같다.
    · 역방향: 하나의 (ticker, country) 는 하나의 IRI 에만 대응한다(co:US-BRK-B vs co:US-BRK.B).
    """
    problems: list[str] = []
    ident: dict[str, tuple[tuple, str]] = {}           # 기업 id → ((ticker, country), 처음 본 파일)
    iri_of: dict[tuple, tuple[str, str]] = {}          # (ticker, country) → (기업 id, 파일)
    for s in sectors:
        for cid, co in sorted(s.companies.items()):
            key = (co.ticker, co.country)
            first = ident.setdefault(cid, (key, s.file))
            if first[0] != key:
                problems.append(f"기업 {cid}: {first[1]} 은 ticker·country {first[0]}, {s.file} 은 {key} — 같아야 한다")
            if co.ticker:
                owner = iri_of.setdefault(key, (cid, s.file))
                if owner[0] != cid:
                    problems.append(f"(ticker, country) {key}: {owner[1]} 은 {owner[0]}, {s.file} 은 {cid} — IRI 가 하나여야 한다")
    return problems


def validate(directory: Path | None = None) -> list[str]:
    """전체 문제 목록. 비어 있으면 통과."""
    sectors, errors = load_all(directory)
    _, _, catalog_problems = load_catalog(directory)
    return errors + catalog_problems + [p for s in sectors for p in s.problems] + _cross_file_problems(sectors)



_l1_memo: tuple[list[Sector], dict[str, tuple[str, str]]] | None = None


def ticker_l1_map(directory: Path | None = None) -> dict[str, tuple[str, str]]:
    """티커(대문자) → (L1 이름, L1 기준색 #hex). ★2026-10-04 시장 리서치·13F 화면 색칠 공용.

    ★규칙: **분류 섹터(kind="taxonomy", generated/tx-*.ttl) 하나 = L1 하나** 만 본다. 테마
      섹터(bio 등)는 L1 이 아니고 색도 없다. 한 티커가 여러 L1 에 있으면 `load_all` 순서
      (파일 이름 순)의 **첫 L1** 을 쓴다 — 결정적이다(2026-10-04 실측 중복 0건).
    ⚠️티커가 없는 기업·분류에 없는 티커(ETF 등)·색이 없는 L1 은 결과에 없다 — 호출부가 색을
      칠하지 않는다. 비슷한 이름으로 추측해 붙이지 않는다.
    ⚠️티커만으로 맞춘다(관심종목 표에 국가가 없다). 분류 생성물은 현재 전부 US 다.
    ★섹터 객체가 그대로면(mtime 캐시 적중) 지난 결과를 재사용한다 — 5초 폴링 경로에서 부른다.
      돌려준 dict 는 공유 객체다. 고치지 말 것.
    """
    global _l1_memo
    sectors, _ = load_all(directory)
    memo = _l1_memo
    if memo is not None and len(memo[0]) == len(sectors) and all(a is b for a, b in zip(memo[0], sectors)):
        return memo[1]
    out: dict[str, tuple[str, str]] = {}
    for s in sectors:
        if s.kind != "taxonomy" or not s.color:
            continue
        for m in s.memberships:
            t = (s.companies[m.company].ticker or "").strip().upper()
            if t:
                out.setdefault(t, (s.name, s.color))
    _l1_memo = (sectors, out)
    return out


def l1_palette(directory: Path | None = None) -> list[tuple[str, str]]:
    """L1 범례 — (이름, 기준색) 목록. 순서는 catalog.ttl 의 묶음 순서(허브와 같다),
    카탈로그에 없는 L1 은 그 뒤에 파일 이름 순. 색이 없는 L1 은 뺀다."""
    sectors, _ = load_all(directory)
    tx = [s for s in sectors if s.kind == "taxonomy" and s.color]
    groups, entries, _ = load_catalog(directory)
    group_order = {g.id: i for i, g in enumerate(groups)}
    rank = {e.code: group_order[e.group] for e in entries if e.group in group_order}
    ordered = sorted(tx, key=lambda s: (s.code not in rank, rank.get(s.code, 0)))   # sorted 는 안정 정렬
    return [(s.name, s.color) for s in ordered if s.color]
