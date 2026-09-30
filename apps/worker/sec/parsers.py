"""SEC 공시 파서 — 13F 정보표 · 13F 표지(정정 종류) · 제출 목록 (계획 A2·A3b).

`parse_infotable` 은 원본 `13F기관내부자/src/parsers/thirteen_f_parser.py` 를 그대로 옮겼다
(네임스페이스·대소문자 섞인 태그 처리 포함). 원본의 `wgt` 계산은 뺐다 — 비중은 분석 단계에서
PRN(채권)·옵션 행을 뺀 뒤 다시 낸다(계획 §A).

⚠️13F 금액(`value`)은 **단위가 섞여 있다** — 2023 이전 공시 대부분이 천 달러, 이후는 달러.
  여기서는 원값 그대로 둔다. 보정은 원본과 같은 규칙(value/shares 중앙값 < 1 이면 ×1000)으로
  분석 단계에서 한다(A5).
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

_XMLNS_DECL_RE = re.compile(r"\sxmlns(?::[A-Za-z_][\w.-]*)?=(\"[^\"]*\"|'[^']*')")
_PREFIXED_ATTR_RE = re.compile(r"\s[A-Za-z_][\w.-]*:[A-Za-z_][\w.-]*=(\"[^\"]*\"|'[^']*')")
_PREFIXED_TAG_RE = re.compile(r"<(/?)[A-Za-z_][\w.-]*:")


def _local_name(name: str) -> str:
    if "}" in name:
        return name.rsplit("}", 1)[1]
    if ":" in name:
        return name.rsplit(":", 1)[1]
    return name


def _parse_xml(xml_text: str) -> ET.Element | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        try:
            root = ET.fromstring(_strip_unbound_prefixes(xml_text))
        except ET.ParseError:
            return None
    for elem in root.iter():
        if isinstance(elem.tag, str):
            elem.tag = _local_name(elem.tag)
        elem.attrib = {_local_name(k) if isinstance(k, str) else k: v for k, v in elem.attrib.items()}
    return root


def _strip_unbound_prefixes(xml_text: str) -> str:
    xml_text = _XMLNS_DECL_RE.sub("", xml_text)
    xml_text = _PREFIXED_ATTR_RE.sub("", xml_text)
    return _PREFIXED_TAG_RE.sub(r"<\1", xml_text)


def _to_float(v: str) -> float | None:
    v = (v or "").strip().replace(",", "")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _find(parent, *tags):
    for t in tags:
        node = parent.find(t)
        if node is not None:  # ⚠️`a or b` 금지 — 자식 없는 노드는 거짓으로 평가된다
            return node
    return None


def _text(elem, tag: str) -> str:
    node = _find(elem, tag, tag.upper(), tag.lower())
    return node.text.strip() if node is not None and node.text else ""


def parse_infotable(xml_text: str) -> list[dict]:
    """13F 정보표 XML → 보유 행 dict 목록(원값)."""
    root = _parse_xml(xml_text)
    if root is None:
        return []
    tables = root.findall(".//infoTable") or root.findall(".//INFOTABLE")
    out = []
    for tbl in tables:
        shr = _find(tbl, "shrsOrPrnAmt", "SHRSORPRNAMTTYPE", "shrsOrPrnAmtType")
        vote = _find(tbl, "votingAuthority", "VOTINGAUTHORITY")
        out.append({
            "name_of_issuer": _text(tbl, "nameOfIssuer"),
            "title_of_class": _text(tbl, "titleOfClass"),
            "cusip": _text(tbl, "cusip"),
            "value": _to_float(_text(tbl, "value")),
            "shares": _to_float(_text(shr, "sshPrnamt")) if shr is not None else None,
            "shr_type": _text(shr, "sshPrnamtType") if shr is not None else "",
            "put_call": _text(tbl, "putCall"),
            "investment_discretion": _text(tbl, "investmentDiscretion"),
            "vote_sole": _to_float(_text(vote, "Sole")) if vote is not None else None,
            "vote_shared": _to_float(_text(vote, "Shared")) if vote is not None else None,
            "vote_none": _to_float(_text(vote, "None")) if vote is not None else None,
        })
    return out


def parse_cover_amendment(xml_text: str) -> tuple[bool, str | None]:
    """13F 표지(primary_doc.xml) → (정정인가, 정정 종류).

    종류는 'RESTATEMENT'(앞 공시를 **대체**) 또는 'NEW HOLDINGS'(비밀유지로 늦게 공개한 **추가분**).
    ⚠️원본은 이 구분 없이 "가장 늦은 공시 하나"만 남겨 버크셔 2023Q3 이 1종목·100% 가 됐다.
    """
    root = _parse_xml(xml_text)
    if root is None:
        return False, None
    is_amend = (root.findtext(".//isAmendment") or "").strip().lower() == "true"
    kind = (root.findtext(".//amendmentType") or "").strip().upper() or None
    if kind and "NEW" in kind:
        kind = "NEW HOLDINGS"
    elif kind and "RESTATE" in kind:
        kind = "RESTATEMENT"
    return is_amend, kind


def pick_infotable(index_json: dict) -> str | None:
    """EDGAR 공시 폴더 `index.json` 에서 정보표 XML 파일명을 고른다(표지 primary_doc 은 제외)."""
    items = ((index_json.get("directory") or {}).get("item")) or []
    names = [i.get("name", "") for i in items]
    for n in names:
        if n.lower().endswith(".xml") and ("infotable" in n.lower() or "informationtable" in n.lower()):
            return n
    for n in names:
        if n.lower().endswith(".xml") and "primary_doc" not in n.lower() and not n.lower().startswith("r"):
            return n
    return None


def submissions_rows(block: dict) -> list[dict]:
    """submissions JSON 의 한 묶음(recent 또는 과거 파일) → 행 목록."""
    keys = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")
    cols = [block.get(k) or [] for k in keys]
    return [dict(zip(keys, vals)) for vals in zip(*cols)]
