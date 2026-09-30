"""Ongoings 「종목 분류체계」(미국 L1→L2→L3) → storage/valuechain/generated/tx-<slug>.ttl 생성.

    .venv/bin/python scripts/valuechain/import_taxonomy.py --source "<…/종목 분류체계>" \
        [--out storage/valuechain/generated] [--check] [--report]

  --source 없으면 환경변수 VC_TAXONOMY_SRC, 둘 다 없으면 exit 2.
  --check  : 쓰지 않고 생성 결과를 디스크의 tx-*.ttl **및 tx-codes.json** 과 비교 — 다르면 exit 1.
  --report : 스킵·정제·경고 요약을 stderr 로.

★생성물이다 — 출력 파일은 매번 **덮어쓴다**(손 편집 금지, 계획 §8 Q1 = A1). 손 보강은 후속 overlay.
★원천 폴더는 읽기만 한다. bio.ttl 등 다른 TTL 도 읽지 않는다(생성물이 손 편집 파일에 의존하지 않음).
★결정적: 같은 입력 → 바이트 동일 출력(정렬 고정, 실행 시각 미기록). 헤더에는 그 L1 입력만의 sha256.

입력(읽기 전용):
  outputs/Classfication.csv(utf-8-sig, 철자 그대로) · work/universe_listings.jsonl(같은 순서) ·
  work/verified_batch_001.jsonl(ISIN → basis·source_url) · work/ticker_changes.jsonl · work/taxonomy_registry.md

규칙(계획 §2 Step 2):
  1. CSV·universe 를 위치로 zip → source=="non_US" 또는 L1 빈 행 먼저 제외(여기서 universe "NULL" 티커 허용)
     → 남은 행의 티커 불일치는 ticker_changes(original→current, 같은 ISIN)로 설명돼야 한다. 아니면 exit 1.
  2. 중복 티커(HON 두 ISIN): 첫 행 유지, 리포트.
  3. 티커 정규화: `BRK/A`→`BRK.A`, `MOGa`→`MOG.A`(assets DB 에 클래스주 없음, form4 는 점 표기 — 2026-09-27 조회).
     IRI co:US-{티커}, vc:exchange/country "US", vc:listed true.
  4. 이름: 티커 변경 행은 current_name, 그 외 CSV 이름에서 증권명 접미사 제거. 무태그 rdfs:label 1개.
  5. 트리: 섹터(L1) → 최상위 분류(L2). L3 는 분류가 아니라 vc:role. L2 코드는 tx-codes.json(추가 전용).
     L1-only 행은 합성 분류 "{prefix}00" "L2 미확정(검증 대기)", order 999.
  6. 멤버십 tx:m-US-{티커}: company·sector·belongsTo=primaryCategory·role(L3 원문)·points(basis)·url·source.
  10. 원자적 쓰기: 같은 디렉터리의 `.<이름>.tmp` → fsync → os.replace. 입력 검증 실패 시 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "storage" / "valuechain" / "generated"
CODES_FILE = "tx-codes.json"
CSV_HEADER = ["티커", "기업이름", "layer1분류", "layer2분류", "layer3분류"]

# L1(레지스트리 라벨) → (slug, 분류 코드 접두어, 영문 이름, 기준색). 12개 고정(레지스트리 "사용자 합의의 12개 L1").
# ★기준색은 섹터(허브 덱·카드 등 띠)와 그 섹터의 모든 L2 에 같이 쓴다 — "L1 섹터별 기준색"(2026-09-28 사용자 요청).
#   배경(#F2F2F2)·브랜드(브라운 #4C2C19·블루 #6390BF)와 어울리게 채도를 낮춘 중간 명도. 흰 글씨가 읽히는 밝기.
L1_META: dict[str, tuple[str, str, str, str]] = {
    "산업재·건설": ("industrials", "I", "Industrials & Construction", "#8A6A45"),      # 브론즈
    "금융": ("financials", "F", "Financials", "#2E5B88"),                              # 네이비
    "재량소비": ("discretionary", "D", "Consumer Discretionary", "#B35F45"),            # 테라코타
    "헬스케어": ("healthcare", "H", "Health Care", "#2F8577"),                          # 틸
    "자원·기초소재": ("materials", "M", "Resources & Basic Materials", "#7A7B3A"),       # 올리브
    "디지털·컴퓨팅": ("digital", "T", "Digital & Computing", "#4F5AA8"),                # 인디고
    "통신·미디어": ("communications", "C", "Communications & Media", "#8757A0"),        # 플럼
    "에너지": ("energy", "E", "Energy", "#B8862B"),                                    # 앰버
    "필수·반복소비": ("staples", "S", "Consumer Staples", "#5B8A45"),                  # 리프
    "부동산": ("realestate", "R", "Real Estate", "#9C5F63"),                           # 로즈우드
    "공공유틸리티": ("utilities", "U", "Utilities", "#3E88AE"),                        # 스틸블루
    "기업서비스": ("bizservices", "B", "Business Services", "#5F6B7A"),                # 슬레이트
}
UNRESOLVED_COLOR = "#7c8490"
UNRESOLVED_LABEL = "L2 미확정(검증 대기)"
UNRESOLVED_SHORT = "L2 미확정"
UNRESOLVED_ORDER = 999

# ── 이름 정제 ────────────────────────────────────────────────────────────────
_ADS = re.compile(
    r"[\s,\-–]*(\(?each representing\b.*|American Deposit[ao]ry (Shares?|Receipts?)\b.*|"
    r"Sponsored ADRs?\b.*|\bADRs?\b.*|\bADSs?\b.*)$", re.I)
_SECURITY = re.compile(
    r"(?:[\s,]+|(?<=\)))(Class [A-Z](-\d+)?\s+|Series [A-Z]\s+)?(Exchangeable\s+)?(New\s+)?"
    r"((Subordinate |Sub\. |Limited |Non-?\s?)?(Voting|Vot\.)\s+)?"
    r"(Common Stock|Common Shares?|Ordinary Shares?|Capital Stock|(Common )?Units?(\s+representing\b.*)?|"
    r"(Common )?Shares of Beneficial Interest|Limited Partner(ship)? Interests?|Registry Shares|"
    r"Representing Limited Partner.*|Shares(\s+Representing\b.*)?)"
    r"(\s*\([^)]*\)|\s+New|\s+REIT|\s+When Issued|\s+Non-?voting|\s+(Class|Cl\.?)\s+[A-Z]\b|"
    r"\s+and\s+Class\b.*|,?\s+\$?[\d.]*\s*par value\b.*|,?\s+no par value)*\s*$", re.I)
# ADS 를 뗀 뒤 남는 "Class A"·"INC-CLASS A"·"CO-NON VOTING"·"Common (Canada)"
_CLASS_TAIL = re.compile(r"([\s,\-]+Class [A-Z](-\d+)?|[\s\-]+Non[\s\-]?Voting|\s+Common(?=\s*\(|$)|(?<=\))\s+REIT)$", re.I)
# 상장 표기용 괄호 꼬리 — 회사명의 일부인 (Cayman)·(1985)·(COPEL) 등은 남긴다.
_QUALIFIER = re.compile(
    r"\s*\((The|New|DE|Delaware|Holding Co(mpany)?|REIT|HC|D/B/A|Canada|Ireland|Switzerland|"
    r"Name to be changed[^)]*)\)$", re.I)


def clean_name(raw: str) -> str:
    """CSV 기업이름 → 증권명 접미사를 뗀 회사명. 빈 결과면 원문. "Boeing Company (The)" → "The Boeing Company"."""
    name = " ".join(raw.split())
    the = False
    for _ in range(4):                   # "X Class A Ordinary Shares (Canada)" 처럼 겹친 꼬리
        new = _CLASS_TAIL.sub("", _SECURITY.sub("", _ADS.sub("", name))).strip().rstrip(",").strip()
        m = _QUALIFIER.search(new)
        if m:
            the = the or m.group(1).lower() == "the"
            new = new[:m.start()].strip()
        if new == name:
            break
        name = new
    if not name:
        return raw.strip()
    return f"The {name}" if the and not name.lower().startswith("the ") else name


# ── 티커 ────────────────────────────────────────────────────────────────────
_TICKER_OK = re.compile(r"^[A-Z0-9]+(\.[A-Z0-9]+)?$")


def normalize_ticker(t: str) -> str:
    """`BRK/A`→`BRK.A`, `MOGa`→`MOG.A`. 결과가 PN_LOCAL 로 안전하지 않으면 ValueError."""
    t = t.strip()
    if "/" in t:
        t = t.replace("/", ".")
    elif m := re.fullmatch(r"([A-Z0-9]+)([a-z])", t):
        t = f"{m.group(1)}.{m.group(2).upper()}"
    if not _TICKER_OK.match(t):
        raise ValueError(f"정규화할 수 없는 티커 {t!r}")
    return t


# ── 레지스트리 ──────────────────────────────────────────────────────────────
_SECTION = re.compile(r"^### (\d+)\. (.+?)\s*$")
_L2_LINE = re.compile(r"^- \*\*(?P<label>[^*]+)\*\*\s*(?:\((?P<l3>[^)]*)\))?\s*:\s*(?P<def>.*)$")
_NOTE = re.compile(r"\s*\((?:\d{4}-\d{2}-\d{2}\s*)?신설[^()]*\)\s*$")


def parse_registry(text: str) -> dict[str, list[tuple[str, str]]]:
    """`### n. <L1>` 12개 절 범위 안의 줄머리 `- **L2**` 만 → {L1: [(L2, 정의)]}(등장 순).

    ★절은 다음 `#`/`##`/`###` 제목에서 끝난다 — 뒤쪽 경계 규칙 절의 `- **…**` 줄은 무시한다.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    cur: str | None = None
    for line in text.splitlines():
        if line.startswith("#"):
            m = _SECTION.match(line)
            cur = m.group(2) if m and m.group(2) in L1_META else None
            if cur is not None:
                out.setdefault(cur, [])
            continue
        if cur is None or not line.startswith("- **"):
            continue
        m = _L2_LINE.match(line)
        if not m:
            raise ValueError(f"레지스트리 L2 줄을 해석할 수 없다: {line[:80]}")
        label = m.group("label").strip()
        definition = _NOTE.sub("", m.group("def").strip()).strip()
        if label not in (lab for lab, _ in out[cur]):
            out[cur].append((label, definition))
    return out


# ── 입력 ────────────────────────────────────────────────────────────────────
class InputError(Exception):
    """입력 검증 실패 — 아무것도 쓰지 않는다."""


@dataclass
class Row:
    ticker: str                          # 정규화 티커
    isin: str
    name: str
    l1: str
    l2: str
    l3: str
    basis: str
    url: str
    raw: dict = field(default_factory=dict)   # 해시용 원 입력


@dataclass
class Report:
    skipped_non_us: int = 0
    skipped_no_l1: int = 0
    duplicates: list[str] = field(default_factory=list)
    renamed: list[str] = field(default_factory=list)
    ticker_normalized: list[str] = field(default_factory=list)
    names_cleaned: int = 0
    names_suspicious: list[str] = field(default_factory=list)
    unknown_l2: list[str] = field(default_factory=list)
    new_codes: list[str] = field(default_factory=list)
    missing_basis: list[str] = field(default_factory=list)
    per_l1: dict[str, int] = field(default_factory=dict)


def _jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_inputs(src: Path, report: Report) -> tuple[list[Row], dict[str, list[tuple[str, str]]]]:
    csv_path = src / "outputs" / "Classfication.csv"
    work = src / "work"
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        table = list(csv.reader(f))
    if not table or table[0] != CSV_HEADER:
        raise InputError(f"CSV 헤더가 {CSV_HEADER} 가 아니다: {table[0] if table else '(빈 파일)'}")
    body = table[1:]
    bad = [i + 2 for i, r in enumerate(body) if len(r) != 5]
    if bad:
        raise InputError(f"CSV 열 수 5 가 아닌 행: {bad[:10]}")
    universe = _jsonl(work / "universe_listings.jsonl")
    if len(body) != len(universe):
        raise InputError(f"CSV 행 수 {len(body)} != universe 행 수 {len(universe)} (원천이 쓰는 중일 수 있다)")
    verified = {v["isin"]: v for v in _jsonl(work / "verified_batch_001.jsonl")}
    changes = {c["isin"]: c for c in _jsonl(work / "ticker_changes.jsonl")}
    registry = parse_registry((work / "taxonomy_registry.md").read_text(encoding="utf-8"))

    rows: list[Row] = []
    seen: dict[str, str] = {}
    for line_no, (r, u) in enumerate(zip(body, universe), start=2):
        csv_ticker, csv_name, l1, l2, l3 = (x.strip() for x in r)
        if u.get("source") == "non_US":
            report.skipped_non_us += 1
            continue
        if not l1:
            report.skipped_no_l1 += 1
            continue
        if l1 not in L1_META:
            raise InputError(f"CSV {line_no}행: 알 수 없는 L1 {l1!r}")
        isin = u["isin"]
        change = changes.get(isin)
        if csv_ticker != u["ticker"]:
            if not (change and change["original_ticker"] == u["ticker"] and change["current_ticker"] == csv_ticker):
                raise InputError(
                    f"CSV {line_no}행: 티커 {csv_ticker!r} ≠ universe {u['ticker']!r}(ticker_changes 로 설명 안 됨) — 정렬 붕괴")
        renamed = bool(change and change["current_ticker"] == csv_ticker)
        try:
            ticker = normalize_ticker(csv_ticker)
        except ValueError as e:
            raise InputError(f"CSV {line_no}행: {e}") from None
        if ticker != csv_ticker:
            report.ticker_normalized.append(f"{csv_ticker}→{ticker}")
        if ticker in seen:
            report.duplicates.append(f"{ticker}: {isin} 스킵(첫 행 {seen[ticker]} 유지)")
            continue
        seen[ticker] = isin
        if renamed:
            name = change["current_name"].strip()
            report.renamed.append(f"{change['original_ticker']}→{ticker} ({name})")
        else:
            name = clean_name(csv_name)
            if name != csv_name.strip():
                report.names_cleaned += 1
            if re.search(r"\b(Stock|Shares?|ADS|ADR|Depositary)\b", name, re.I):
                report.names_suspicious.append(f"{ticker}: {name}")
        v = verified.get(isin, {})
        basis = (v.get("basis") or "").strip()
        url = (v.get("source_url") or "").strip()
        if not basis:
            report.missing_basis.append(ticker)
        if re.search(r'[\s<>"{}|\\^`]', url):
            raise InputError(f"CSV {line_no}행: source_url 에 IRI 로 쓸 수 없는 문자 {url!r}")
        rows.append(Row(
            ticker=ticker, isin=isin, name=name, l1=l1, l2=l2, l3=l3, basis=basis, url=url,
            raw={"csv": list(r), "isin": isin, "basis": basis, "url": url,
                 "current_name": change["current_name"] if renamed else None},
        ))
    return rows, registry


# ── 코드 ────────────────────────────────────────────────────────────────────
def assign_codes(rows: list[Row], registry: dict[str, list[tuple[str, str]]],
                 codes: dict[str, dict[str, str]], report: Report) -> dict[str, dict[str, str]]:
    """tx-codes.json 갱신본. **추가 전용** — 있는 코드는 바꾸지 않고, 새 L2 는 다음 번호.

    레지스트리 L2 를 레지스트리 순으로 먼저, 레지스트리 밖 L2(CSV 에만 있음)는 이름순으로 뒤에."""
    out = {slug: dict(m) for slug, m in codes.items()}
    used: dict[str, set[str]] = {}
    for r in rows:
        if r.l2:
            used.setdefault(r.l1, set()).add(r.l2)
    for l1, (slug, prefix, _, _) in L1_META.items():
        reg_labels = [lab for lab, _ in registry.get(l1, [])]
        extra = sorted(used.get(l1, set()) - set(reg_labels))
        if not reg_labels and not extra:
            continue
        m = out.setdefault(slug, {})
        for label in reg_labels + extra:
            if label in m:
                continue
            nums = [int(c[len(prefix):]) for c in m.values() if c.startswith(prefix) and c[len(prefix):].isdigit()]
            code = f"{prefix}{max(nums, default=0) + 1:02d}"
            m[label] = code
            report.new_codes.append(f"{slug}: {label} = {code}")
    return out


def dump_codes(codes: dict[str, dict[str, str]]) -> str:
    """L1 순(레지스트리 순) → 코드 순. 결정적."""
    slugs = [slug for slug, _, _, _ in L1_META.values()]
    ordered = {slug: dict(sorted(codes[slug].items(), key=lambda kv: kv[1]))
               for slug in sorted(codes, key=lambda k: (slugs.index(k) if k in slugs else len(slugs), k))}
    return json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"


# ── TTL ─────────────────────────────────────────────────────────────────────
def esc(s: str) -> str:
    """Turtle 문자열 리터럴 이스케이프(단일 함수)."""
    return (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))


def build_sector(l1: str, rows: list[Row], registry_entries: list[tuple[str, str]],
                 codes: dict[str, str], report: Report) -> str:
    slug, prefix, en, color = L1_META[l1]
    reg_order = {lab: i + 1 for i, (lab, _) in enumerate(registry_entries)}
    definition = dict(registry_entries)

    # 쓰이는 L2 만 분류로 만든다(빈 분류 섹션 방지). 코드는 tx-codes.json 에 이미 전부 있다.
    used = sorted({r.l2 for r in rows if r.l2})
    extra = sorted(lab for lab in used if lab not in reg_order)
    for lab in extra:
        report.unknown_l2.append(f"{l1} > {lab} (레지스트리에 없음 — 뒤에 이름순)")
    order_of = {lab: reg_order[lab] if lab in reg_order else len(registry_entries) + 1 + extra.index(lab)
                for lab in used}
    cats: list[tuple[str, str, int, str, str | None]] = []   # (code, label, order, color, comment)
    for lab in sorted(used, key=lambda x: order_of[x]):
        cats.append((codes[lab], lab, order_of[lab], color,
                     definition.get(lab) or None))
    has_unresolved = any(not r.l2 for r in rows)
    if has_unresolved:
        cats.append((f"{prefix}00", UNRESOLVED_LABEL, UNRESOLVED_ORDER, UNRESOLVED_COLOR,
                     "원천에서 L1 만 검증되고 L2 가 아직 정해지지 않은 기업."))
    cat_code = {lab: codes[lab] for lab in used}

    # 헤더 해시: 이 L1 의 입력만(정렬된 행 + 레지스트리 절 + 코드) — 다른 L1 변경이 이 파일을 흔들지 않는다.
    payload = json.dumps({
        "rows": sorted((r.raw for r in rows), key=lambda x: x["isin"]),
        "registry": registry_entries, "codes": dict(sorted(codes.items())),
    }, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    ns = f"http://ge.local/valuechain/tx-{slug}#"
    out: list[str] = [
        "# GENERATED by scripts/valuechain/import_taxonomy.py — DO NOT EDIT (다음 실행에서 덮어쓴다).",
        "# 원천: Ongoings/종목 분류체계(outputs/Classfication.csv · work/*.jsonl · work/taxonomy_registry.md).",
        "# 고치려면 원천을 고치고 다시 생성한다. 손 보강은 후속 overlay(storage/valuechain/README.md).",
        "# vc-generated: taxonomy",
        f"# vc-input: rows={len(rows)} sha256={digest}",
        "",
        "@prefix vc:   <http://ge.local/valuechain#> .",
        "@prefix co:   <http://ge.local/company#> .",
        f"@prefix tx:   <{ns}> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "",
        "# ── 섹터 ───────────────────────────────────────────────────────────────────",
        "tx:Sector a vc:Sector ;",
        f'    vc:code "tx-{slug}" ; vc:kind "taxonomy" ; vc:color "{color}" ;',
        f'    rdfs:label "{esc(l1)}"@ko , "{esc(en)}"@en ;',
        f'    rdfs:comment "미국 상장 운영기업 3계층 분류의 L1 「{esc(l1)}」. 대분류 = L2, 카드 역할 줄 = L3(후보 포함), '
        f'포인트 = 판정 근거."@ko .',
        "",
        "tx:src a vc:Source ; vc:order 1 ;",
        '    vc:code "분류체계" ;',
        '    rdfs:label "Ongoings/종목 분류체계 — outputs/Classfication.csv · work/verified_batch_001.jsonl"@ko ;',
        '    rdfs:comment "기업별 IR·SEC 근거 URL 은 카드의 근거 링크."@ko .',
        "",
        "# ── 분류(L2) ───────────────────────────────────────────────────────────────",
    ]
    for code, label, order, color, comment in cats:
        out.append(f"tx:{code} a vc:Category ;")
        out.append("    vc:subCategoryOf tx:Sector ;")
        out.append(f'    vc:code "{code}" ; vc:order {order} ; vc:color "{color}" ;')
        short = UNRESOLVED_SHORT if order == UNRESOLVED_ORDER else label
        out.append(f'    rdfs:label "{esc(label)}"@ko ; vc:shortLabel "{esc(short)}"'
                   + (" ;" if comment else " ."))
        if comment:
            out.append(f'    rdfs:comment "{esc(comment)}"@ko .')
    out.append("")
    out.append("# ── 기업 · 멤버십 ─────────────────────────────────────────────────────────")
    for code, label, *_ in cats:
        members = sorted((r for r in rows if (cat_code[r.l2] if r.l2 else f"{prefix}00") == code),
                         key=lambda r: r.ticker)
        if not members:
            continue
        out.append("")
        out.append(f"# ━━ {code} {label} ━━")
        for r in members:
            local = f"US-{r.ticker}"
            out.append("")
            out.append(f"co:{local} a vc:Company ;")
            out.append(f'    rdfs:label "{esc(r.name)}" ;')
            out.append(f'    vc:ticker "{r.ticker}" ; vc:exchange "US" ; vc:country "US" ; vc:listed true ;')
            out.append(f'    vc:isin "{esc(r.isin)}" .')
            out.append(f"tx:m-{local} a vc:Membership ;")
            out.append(f"    vc:company co:{local} ; vc:sector tx:Sector ;")
            out.append(f"    vc:primaryCategory tx:{code} ; vc:belongsTo tx:{code} ;")
            if r.l3:
                out.append(f'    vc:role "{esc(r.l3)}" ;')
            if r.basis:
                out.append(f'    vc:points ( "{esc(r.basis)}" ) ;')
            if r.url:
                out.append(f'    vc:url "{esc(r.url)}"^^xsd:anyURI ;')
            out.append("    vc:source tx:src .")
    report.per_l1[l1] = len(rows)
    return "\n".join(out) + "\n"


def generate(src: Path, codes: dict[str, dict[str, str]], report: Report) -> dict[str, str]:
    """{파일 이름: 내용} — tx-<slug>.ttl 들과 tx-codes.json. 입력 오류는 InputError."""
    rows, registry = read_inputs(src, report)
    missing = [l1 for l1 in L1_META if l1 not in registry]
    if missing:
        raise InputError(f"레지스트리에 L1 절이 없다: {missing}")
    new_codes = assign_codes(rows, registry, codes, report)
    files: dict[str, str] = {}
    for l1, (slug, _, _, _) in L1_META.items():
        l1_rows = [r for r in rows if r.l1 == l1]
        if not l1_rows:
            continue
        files[f"tx-{slug}.ttl"] = build_sector(l1, l1_rows, registry[l1], new_codes[slug], report)
    files[CODES_FILE] = dump_codes(new_codes)
    return files


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.parent / f".{path.name}.tmp"          # 점 접두 → 로더 glob 이 읽지 않는다
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def print_report(report: Report, files: dict[str, str]) -> None:
    w = lambda s="": print(s, file=sys.stderr)  # noqa: E731
    total = sum(report.per_l1.values())
    w(f"[import_taxonomy] 멤버십 {total} · 섹터 파일 {sum(1 for n in files if n.endswith('.ttl'))}")
    for l1, n in sorted(report.per_l1.items(), key=lambda kv: -kv[1]):
        w(f"  {L1_META[l1][0]:<15} {l1:<10} {n}")
    w(f"스킵: non_US {report.skipped_non_us} · L1 빈 행 {report.skipped_no_l1} · 중복 티커 {len(report.duplicates)}")
    for d in report.duplicates:
        w(f"  중복 {d}")
    w(f"티커 정규화 {len(report.ticker_normalized)}: {', '.join(report.ticker_normalized)}")
    w(f"티커 변경(current_name) {len(report.renamed)}: {'; '.join(report.renamed)}")
    w(f"이름 정제 {report.names_cleaned}건")
    for s in report.names_suspicious:
        w(f"  ⚠️ 접미사 의심 {s}")
    for s in report.unknown_l2:
        w(f"  ⚠️ {s}")
    w(f"새 L2 코드 {len(report.new_codes)}")
    for s in report.new_codes:
        w(f"  + {s}")
    if report.missing_basis:
        w(f"⚠️ basis 없음 {len(report.missing_basis)}: {', '.join(report.missing_basis[:20])}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", default=os.environ.get("VC_TAXONOMY_SRC"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if not args.source:
        print("--source 또는 VC_TAXONOMY_SRC 가 필요하다", file=sys.stderr)
        return 2
    src, out = Path(args.source), Path(args.out)
    codes_path = out / CODES_FILE
    codes = json.loads(codes_path.read_text(encoding="utf-8")) if codes_path.exists() else {}
    report = Report()
    try:
        files = generate(src, codes, report)
    except (InputError, OSError, KeyError, json.JSONDecodeError) as e:
        print(f"입력 검증 실패 — 아무것도 쓰지 않았다: {e}", file=sys.stderr)
        return 1
    if args.report:
        print_report(report, files)
    stale = sorted(p.name for p in out.glob("tx-*.ttl") if p.name not in files) if out.exists() else []

    if args.check:
        diff = [n for n, c in files.items()
                if not (out / n).exists() or (out / n).read_bytes() != c.encode("utf-8")] + stale
        for n in diff:
            print(f"다름: {n}", file=sys.stderr)
        print("check: OK" if not diff else f"check: 다름 {len(diff)}건", file=sys.stderr)
        return 1 if diff else 0

    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob(".*.tmp"):                     # 지난 실행이 남긴 임시 파일
        p.unlink()
    written = 0
    for name, content in files.items():
        path = out / name
        if path.exists() and path.read_bytes() == content.encode("utf-8"):
            continue                                  # 같으면 쓰지 않는다(mtime 보존 → 로더 캐시 유지)
        _atomic_write(path, content)
        written += 1
    for name in stale:                               # 원천에서 사라진 L1 의 옛 생성물
        (out / name).unlink()
    print(f"[import_taxonomy] {out}: 파일 {len(files)}개 중 {written}개 갱신, 오래된 파일 {len(stale)}개 삭제",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
