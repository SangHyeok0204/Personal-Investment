"""bio_data.json → storage/valuechain/bio.ttl 1회성 변환 (계획 §5.1, §12-5).

이 변환 뒤로는 **bio.ttl 이 정본**이다 — 사람이 직접 고친다. 이 스크립트를 다시 돌리면
손으로 고친 내용이 덮이니, 원본 JSON 을 새로 받아 처음부터 다시 만들 때만 쓴다.

    .venv/bin/python scripts/valuechain/bio_json_to_ttl.py "<...>/10_밸류체인맵/bio_data.json"

정제 규칙(바뀐 행은 전부 리포트에 찍힌다):
  1. 결합 행 "A / B"(이름을 " / " 로 분리) → 기업을 따로 만든다. role·points·src·소속 분류는
     복제한다.
     · 티커도 " / " 로 같은 개수만큼 나뉘면 순서대로 짝짓는다(GEHC / PHG).
     · 티커가 1개면 그 티커의 주인을 `TICKER_OWNER` 표로 정하고 나머지는 비상장이다
       (Epic / Oracle → Oracle=ORCL, Epic=비상장).
     · 모회사-자회사 묶음은 `NO_SPLIT` 에 두고 나누지 않는다(한 상장사다).
     · 국가도 " / " 가 아니라 "/" 로 이름 개수만큼 나뉘면 순서대로, 아니면 첫 국가
       (`PART_COUNTRY` 로 개별 보정).
  2. 국가 복수("US/CN") → 첫 국가를 vc:country, 나머지는 vc:otherCountry(분리된 행 제외).
  3. 티커 "비상장"·"오픈소스"·"" → vc:listed false, IRI co:{국가}-x-{slug}.
     slug = 영문명(없으면 이름)을 소문자로, 영숫자·한글 외 문자는 하이픈.
  4. "MGI: 688114"·"큐렉소 060280" 처럼 이름이 붙은 티커 → 심볼만 뽑는다(마지막 토큰).
  5. 거래소 접미사 ".HK" → 숫자만 남기고 HKEX. 그 외 거래소는 국가·티커 모양으로 추정
     (`exchange_of`): KR 6자리 → KRX, CN 6자리 → SSE, JP 4자리 → TSE, US → US(구분 안 함) …
     미국에만 상장된 외국 기업은 `EXCHANGE_OVERRIDE`.
  6. 정제 뒤 IRI 가 겹치면 한 기업으로 합친다(소속 분류·포인트·출처 합집합).

기업 IRI = co:{국가}-{티커}. 멤버십 IRI = bio:m-{기업 IRI 로컬명}.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "storage" / "valuechain" / "bio.ttl"

# 최상위 분류 색(원본 template.html 의 라이트 모드 --cA … --cC).
COLORS = {"A": "#23865f", "B-1": "#6a55c9", "B-2": "#2877b5", "B-3": "#c24f78", "C": "#a97b12"}

UNLISTED = {"비상장", "오픈소스", ""}
# 모회사-자회사 묶음 — 상장사 하나다.
NO_SPLIT = {"Gilead / Kite", "Google DeepMind / Isomorphic"}
# 결합 행에 티커가 1개뿐일 때 그 티커의 주인(나머지는 비상장 — 원본 points 에 적혀 있다).
TICKER_OWNER = {
    "Epic / Oracle": "Oracle",
    "Tecan / Opentrons": "Tecan",
    "Seres / Vedanta": "Seres",
    "Ultima / MGI": "MGI",
    "CMR Surgical / 큐렉소": "큐렉소",
    "Cutera / Candela / Lumenis": "Cutera",
}
# 국가 개수가 이름 개수와 안 맞을 때의 개별 보정.
PART_COUNTRY = {"Lumenis": "IL"}
# 국가로 추정하면 틀리는 것 — 미국에만 상장된 외국 기업.
EXCHANGE_OVERRIDE = {"BNTX": "NASDAQ", "INMD": "NASDAQ", "ICLR": "NASDAQ", "MESO": "NASDAQ", "LEGN": "NASDAQ"}
COUNTRY_EXCHANGE = {
    "US": "US", "KR": "KRX", "HK": "HKEX", "JP": "TSE", "CH": "SIX", "DE": "XETRA", "UK": "LSE",
    "DK": "CPH", "AU": "ASX", "NL": "EURONEXT", "BE": "EURONEXT",
}

report: list[str] = []


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "-", s.lower()).strip("-")


def exchange_of(ticker: str, country: str) -> str | None:
    if ticker in EXCHANGE_OVERRIDE:
        return EXCHANGE_OVERRIDE[ticker]
    if country == "CN" and re.fullmatch(r"\d{6}", ticker):
        return "SSE" if ticker.startswith("6") else "SZSE"
    return COUNTRY_EXCHANGE.get(country)


def clean_ticker(raw: str, country: str) -> tuple[str | None, str | None]:
    """(티커, 거래소). 비상장이면 (None, None)."""
    t = raw.strip()
    if t in UNLISTED:
        return None, None
    if " " in t or ":" in t:                       # 규칙 4
        t = re.split(r"[\s:]+", t)[-1]
    if t.endswith(".HK"):                          # 규칙 5
        return t[:-3], "HKEX"
    return t, exchange_of(t, country)


def split_row(row: dict) -> list[dict]:
    """규칙 1·2 — 결합 행을 기업별 dict 로. 각 dict 에 name/en/ticker_raw/country/other 를 채운다."""
    countries = row["country"].split("/")
    names = [row["name"]] if row["name"] in NO_SPLIT else row["name"].split(" / ")
    if len(names) == 1:
        return [dict(row, ticker_raw=row["ticker"], country=countries[0], other=countries[1:])]
    tickers = row["ticker"].split(" / ")
    if len(tickers) != len(names):
        owner = TICKER_OWNER.get(row["name"])
        if owner is None and row["ticker"] not in UNLISTED:
            sys.exit(f"결합 행 티커 주인을 모름 — TICKER_OWNER 에 추가: {row['name']!r} {row['ticker']!r}")
        tickers = [row["ticker"] if n == owner else "비상장" for n in names]
    parts = []
    for i, (n, t) in enumerate(zip(names, tickers)):
        c = countries[i] if len(countries) == len(names) else countries[0]
        c = PART_COUNTRY.get(n, c)
        parts.append(dict(row, name=n, en="", ticker_raw=t, country=c, other=[]))
    report.append(
        f"[분리] {row['name']} ({row['ticker'] or '-'}, {row['country']}) → "
        + ", ".join(f"{p['name']}({p['ticker_raw']}, {p['country']})" for p in parts)
    )
    return parts


def build(data: dict) -> tuple[list[dict], dict[str, str]]:
    src_iri = {}
    for i, s in enumerate(data["sources"], 1):
        src_iri.setdefault(s["tag"], f"bio:src-{i:02d}")

    companies: dict[str, dict] = {}
    for row in data["companies"]:
        for p in split_row(row):
            ticker, exch = clean_ticker(p["ticker_raw"], p["country"])
            if ticker is None:
                local = f"{p['country']}-x-{slug(p['en'] or p['name'])}"
                report.append(f"[비상장] {p['name']}: 티커 {p['ticker_raw']!r} → listed false, co:{local}")
            else:
                local = f"{p['country']}-{ticker}"
                if ticker != p["ticker_raw"]:
                    report.append(f"[티커] {p['name']}: {p['ticker_raw']!r} → {ticker} ({exch})")
            if p["other"]:
                report.append(f"[국가] {p['name']}: {row['country']} → {p['country']} + otherCountry {'/'.join(p['other'])}")
            if local in companies:                 # 규칙 6
                c = companies[local]
                c["subs"] += [s for s in p["subs"] if s not in c["subs"]]
                c["points"] += [x for x in p["points"] if x not in c["points"]]
                c["src"] += [x for x in p["src"] if x not in c["src"]]
                report.append(f"[병합] {p['name']} → co:{local} 에 합침")
                continue
            companies[local] = dict(
                local=local, name=p["name"], en=p["en"], ticker=ticker, exchange=exch,
                country=p["country"], other=p["other"], subs=list(p["subs"]),
                role=p["role"], points=list(p["points"]), src=list(p["src"]),
            )
    return list(companies.values()), src_iri


def lit(s: str, lang: str | None = None) -> str:
    esc = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{esc}"' + (f"@{lang}" if lang else "")


def cat_iri(code: str) -> str:
    return f"bio:{code}"


def render(data: dict, companies: list[dict], src_iri: dict[str, str]) -> str:
    out = [
        "@prefix vc:   <http://ge.local/valuechain#> .",
        "@prefix co:   <http://ge.local/company#> .",
        "@prefix bio:  <http://ge.local/valuechain/bio#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        "#" * 77,
        "# 바이오 섹터 밸류체인 — 이 파일이 정본이다(사람이 직접 고친다).",
        "#",
        "# 처음 한 번 scripts/valuechain/bio_json_to_ttl.py 로 bio_data.json 에서 만들었다.",
        "# 새 섹터는 이 파일을 복사해 내용을 바꾸면 된다(README.md). 스키마는 core.ttl.",
        "# 관계는 한 방향만 쓴다: subCategoryOf(하위→상위), belongsTo(멤버십→분류), feedsInto.",
        "#" * 77,
        "",
        "# ── 섹터 ───────────────────────────────────────────────────────────────────",
        "bio:Bio a vc:Sector ;",
        '    vc:code "bio" ;',
        '    rdfs:label "바이오"@ko , "Bio"@en ;',
        '    rdfs:comment "AI 바이오 밸류체인: 인프라 → 신약·진단·기기 → 임상·생산."@ko .',
        "",
        "# ── 분류(대분류 → 중분류) ─────────────────────────────────────────────────",
    ]
    subs_by_cat: dict[str, list[dict]] = {}
    for s in data["subs"]:
        subs_by_cat.setdefault(s["cat"], []).append(s)
    for i, c in enumerate(data["categories"], 1):
        out += [
            "",
            f"{cat_iri(c['id'])} a vc:Category ;",
            "    vc:subCategoryOf bio:Bio ;",
            f"    vc:code {lit(c['id'])} ; vc:order {i} ; vc:color {lit(COLORS[c['id']])} ;",
            f"    rdfs:label {lit(c['name'], 'ko')} ; vc:shortLabel {lit(c['short'])} ;",
            f"    rdfs:comment {lit(c['desc'], 'ko')} .",
        ]
        for j, s in enumerate(subs_by_cat.get(c["id"], []), 1):
            lines = [
                f"{cat_iri(s['id'])} a vc:Category ;",
                f"    vc:subCategoryOf {cat_iri(c['id'])} ;",
                f"    vc:code {lit(s['id'])} ; vc:order {j} ;",
                f"    rdfs:label {lit(s['name'], 'ko')} ;",
                f"    rdfs:comment {lit(s['desc'], 'ko')}",
            ]
            if s["market"]:
                lines[-1] += " ;"
                lines.append(f"    vc:marketSize {lit(s['market'])}")
            lines[-1] += " ."
            out += lines

    out += ["", "# ── 흐름(밸류체인 단계 A → B) ─────────────────────────────────────────────", ""]
    targets: dict[str, list[str]] = {}
    for a, b in data["flows"]:
        targets.setdefault(a, []).append(b)
    for a, bs in targets.items():
        out.append(f"{cat_iri(a)} vc:feedsInto {' , '.join(cat_iri(b) for b in bs)} .")

    out += ["", "# ── 자료(출처 태그) ───────────────────────────────────────────────────────"]
    for i, s in enumerate(data["sources"], 1):
        iri = f"bio:src-{i:02d}"
        out += [
            "",
            f"{iri} a vc:Source ; vc:order {i} ;",
            f"    vc:code {lit(s['tag'])} ;",
            f"    rdfs:label {lit(s['file'], 'ko')} ;",
            f"    rdfs:comment {lit(s['note'], 'ko')} .",
        ]

    out += ["", "# ── 핵심 논지 ─────────────────────────────────────────────────────────────"]
    for i, t in enumerate(data["theses"], 1):
        out += [
            "",
            f"bio:thesis-{i} a vc:Thesis ; vc:order {i} ;",
            f"    rdfs:label {lit(t['src'], 'ko')} ;",
            f"    rdfs:comment {lit(t['text'], 'ko')} .",
        ]

    out += [
        "",
        "# ── 기업 · 멤버십 ─────────────────────────────────────────────────────────",
        "# 기업(co:) = 섹터 불문 신원. 멤버십(bio:m-…) = 이 섹터에서의 소속·역할·포인트·출처.",
        "# 주 소속(primaryCategory) 중분류별로 묶었다.",
    ]
    sub_name = {s["id"]: s["name"] for s in data["subs"]}
    for s in data["subs"]:
        members = [c for c in companies if c["subs"][0] == s["id"]]
        if not members:
            continue
        out += ["", f"# ━━ {s['id']} {sub_name[s['id']]} ━━"]
        for c in members:
            co = [f"co:{c['local']} a vc:Company ;", f"    rdfs:label {lit(c['name'], 'ko')}"]
            if c["en"]:
                co[-1] += f" , {lit(c['en'], 'en')}"
            co[-1] += " ;"
            if c["ticker"]:
                co.append(f"    vc:ticker {lit(c['ticker'])} ; vc:exchange {lit(c['exchange'])} ;")
            co.append(f"    vc:country {lit(c['country'])} ;")
            for o in c["other"]:
                co.append(f"    vc:otherCountry {lit(o)} ;")
            co.append(f"    vc:listed {'true' if c['ticker'] else 'false'} .")
            m = [
                f"bio:m-{c['local']} a vc:Membership ;",
                f"    vc:company co:{c['local']} ; vc:sector bio:Bio ;",
                f"    vc:primaryCategory {cat_iri(c['subs'][0])} ;",
                f"    vc:belongsTo {' , '.join(cat_iri(x) for x in c['subs'])} ;",
                f"    vc:role {lit(c['role'])} ;",
            ]
            if c["points"]:
                m.append("    vc:points (")
                m += [f"        {lit(p)}" for p in c["points"]]
                m.append("    ) ;")
            srcs = [src_iri[t] for t in c["src"]]
            if srcs:
                m.append(f"    vc:source {' , '.join(srcs)} ;")
            m[-1] = m[-1][:-2] + " ."
            out += [""] + co + m
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json_path", type=Path)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    data = json.loads(args.json_path.read_text(encoding="utf-8"))
    companies, src_iri = build(data)
    args.out.write_text(render(data, companies, src_iri), encoding="utf-8")

    print("정제 리포트")
    for line in report:
        print("  " + line)
    print(
        f"\n원본 기업 행 {len(data['companies'])} → 기업 {len(companies)}"
        f" (상장 {sum(1 for c in companies if c['ticker'])}, 비상장 {sum(1 for c in companies if not c['ticker'])})"
        f" · 분류 {len(data['categories'])}+{len(data['subs'])} · 흐름 {len(data['flows'])}"
        f" · 논지 {len(data['theses'])} · 자료 {len(data['sources'])}"
    )
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
