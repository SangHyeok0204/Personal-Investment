"""Form 4(내부자 거래) · Schedule 13D/13G(대량 보유) 파서 — 계획 A3b.

원본 `13F기관내부자/src/parsers/{form4_parser, thirteen_dg_parser}.py` 를 옮겼다. 바꾼 것:

★Form 4 **공동 신고**: 원본은 첫 보고자(reportingOwner)만 읽었다 — 공동 신고의 나머지 사람이
  사라져 "여러 임원이 동시에 샀다"가 적게 셌다(계획 §A 리뷰 지적). 그렇다고 보고자마다 거래 행을
  복제하면 **같은 주식이 보고자 수만큼 곱해져** 순매수가 부푼다(공동 신고는 대개 같은 지분을 펀드와
  운용역이 함께 신고한 것이다). → 거래 행은 한 번만 두고, 보고자 **전원**을 이름·CIK 목록으로 붙인다
  (`insider_name` = "A; B", `owners` = [{cik, name, role}, …]).
"""
from __future__ import annotations

import re
from datetime import date
from xml.etree import ElementTree as ET

# 거래 코드 → 방향·분류. 순매수는 비파생 · P/S · 계획매매 아님만 센다(계획 §A-2).
TRANSACTION_CODE_MAP: dict[str, dict] = {
    "P": {"buy_sell": "BUY", "is_open_market": True, "label": "공개시장 매수"},
    "S": {"buy_sell": "SELL", "is_open_market": True, "label": "공개시장 매도"},
    "A": {"buy_sell": "NEUTRAL", "label": "무상취득(보상)"},
    "M": {"buy_sell": "NEUTRAL", "is_option_exercise": True, "label": "옵션 행사"},
    "F": {"buy_sell": "NEUTRAL", "label": "세금 원천징수"},
    "G": {"buy_sell": "NEUTRAL", "label": "증여"},
}
# ★직원주식매입(ESPP)도 계획매매다 — 회사 관리자가 정해진 조건으로 대신 사 준다(본인 판단 아님).
#   ⚠️2026-10-04: TSMC 임직원 32명의 ESPP 매입(코드 P)이 '여러 임원 동시 매수 31명'으로 떴다
#   (2026-03 부터 외국 발행사 임원도 Form 4 를 낸다).
#   ⚠️**매수(P)에만** 적용한다 — 매도 각주의 "ESPP 로 취득한 주식"은 출처 설명일 뿐, 파는 건 본인 판단이다.
_PLANNED_KEYWORDS = ("10b5-1", "10b5–1", "rule 10b5")
_ESPP_KEYWORDS = ("employee stock purchase plan", "(espp)")


def cik10(v) -> str | None:
    v = re.sub(r"\D", "", str(v or ""))
    return v.zfill(10) if v else None


def _date(v) -> date | None:
    """'2026-09-01' · '09/01/2026'(13D/G 표지) → date."""
    v = (v or "").strip()[:10]
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", v)
    if m:
        v = f"{m[3]}-{m[1]}-{m[2]}"
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def _num(v) -> float | None:
    v = (v or "").strip().replace(",", "").replace("%", "")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _role(rel: ET.Element | None) -> str | None:
    if rel is None:
        return None
    yes = lambda tag: (rel.findtext(tag) or "").strip() in ("1", "true")  # noqa: E731
    roles = []
    if yes("isDirector"):
        roles.append("Director")
    if yes("isOfficer"):
        title = (rel.findtext("officerTitle") or "").strip()
        roles.append(f"Officer ({title})" if title else "Officer")
    if yes("isTenPercentOwner"):
        roles.append("10% Owner")
    if yes("isOther"):
        other = (rel.findtext("otherText") or "").strip()
        roles.append(f"Other ({other})" if other else "Other")
    return ", ".join(roles) or None


def parse_form4(xml_text: str) -> tuple[list[dict], list[dict]]:
    """Form 4 XML → (거래 행들, 보고자 전원). 거래 행은 보고자 수와 무관하게 거래당 한 행."""
    root = ET.fromstring(xml_text)
    issuer_cik = cik10(root.findtext("issuer/issuerCik"))
    issuer_name = (root.findtext("issuer/issuerName") or "").strip() or None
    ticker = (root.findtext("issuer/issuerTradingSymbol") or "").strip().upper() or None

    owners = []
    for ro in root.findall(".//reportingOwner"):
        oid = ro.find("reportingOwnerId")
        owners.append({
            "cik": cik10(oid.findtext("rptOwnerCik")) if oid is not None else None,
            "name": ((oid.findtext("rptOwnerName") or "").strip() or None) if oid is not None else None,
            "role": _role(ro.find("reportingOwnerRelationship")),
        })
    names = [o["name"] for o in owners if o["name"]]
    context = {
        "issuer_cik": issuer_cik, "issuer_name": issuer_name, "ticker": ticker,
        "insider_cik": owners[0]["cik"] if owners else None,
        "insider_name": "; ".join(names) or None,
        "insider_role": "; ".join(dict.fromkeys(o["role"] for o in owners if o["role"])) or None,
    }

    footnotes = {fn.get("id", ""): (fn.text or "").strip() for fn in root.findall(".//footnotes/footnote")}
    planned_ids = {fid for fid, txt in footnotes.items() if any(k in txt.lower() for k in _PLANNED_KEYWORDS)}
    espp_ids = {fid for fid, txt in footnotes.items() if any(k in txt.lower() for k in _ESPP_KEYWORDS)}
    aff = root.find(".//aff10b5One")
    doc_planned = aff is not None and (aff.text or "").strip() in ("1", "true")

    rows = []
    for table, derivative in ((".//nonDerivativeTable/nonDerivativeTransaction", False),
                              (".//derivativeTable/derivativeTransaction", True)):
        for tx in root.findall(table):
            code = (tx.findtext("transactionCoding/transactionCode") or "").strip()
            m = TRANSACTION_CODE_MAP.get(code, {})
            shares = _num(tx.findtext("transactionAmounts/transactionShares/value"))
            price = _num(tx.findtext("transactionAmounts/transactionPricePerShare/value"))
            refs = {f.get("id") for f in tx.findall(".//footnoteId") if f.get("id")}
            title = (tx.findtext("securityTitle/value") or "").strip()
            desc = " | ".join([p for p in [title, m.get("label")] if p] +
                              [f"[{f}] {footnotes[f]}" for f in sorted(refs) if footnotes.get(f)]) or None
            rows.append({
                **context,
                "transaction_date": _date(tx.findtext("transactionDate/value")),
                "transaction_code": code or None,
                "transaction_description": desc[:1000] if desc else None,
                "buy_sell": m.get("buy_sell", "NEUTRAL"),
                "shares": shares, "price": price,
                "transaction_value": shares * price if shares is not None and price is not None else None,
                "shares_owned_after": _num(tx.findtext("postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                "ownership_type": (tx.findtext("ownershipNature/directOrIndirectOwnership/value") or "").strip() or None,
                "acquired_disposed": (tx.findtext("transactionAmounts/transactionAcquiredDisposedCode/value") or "").strip()[:1] or None,
                "is_derivative": derivative,
                "is_open_market": bool(m.get("is_open_market")),
                "is_option_exercise": bool(m.get("is_option_exercise")),
                "is_planned_trade": doc_planned or bool(refs & planned_ids) or (code == "P" and bool(refs & espp_ids)),
            })
    return rows, owners


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _first(root: ET.Element, names: set[str]) -> str | None:
    low = {n.lower() for n in names}
    for el in root.iter():
        if isinstance(el.tag, str) and _local(el.tag).lower() in low and (el.text or "").strip():
            return el.text.strip()
    return None


def parse_13dg(xml_text: str) -> dict | None:
    """13D/13G 표지 XML → 보유 이벤트 하나(관용적 추출). 구형 텍스트 공시 등 못 읽으면 None."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    subject = _first(root, {"nameOfIssuer", "issuerName", "subjectCompanyName", "companyConformedName"})
    cusip = _first(root, {"cusip", "cusipNumber", "issuerCusip", "issuerCusipNumber"})
    percent = _num(_first(root, {"percentOfClass", "percentOwned", "percentage", "classPercent"}))
    shares = _num(_first(root, {"aggregateAmountOwned", "amountBeneficiallyOwned", "aggregateAmount",
                                "sharesBeneficiallyOwned"}))
    if not any([subject, cusip, percent, shares]):
        return None
    return {
        "subject_name": subject,
        "subject_cik": cik10(_first(root, {"issuerCik", "subjectCik"})),
        "cusip": (cusip or "")[:9] or None,
        "percent": percent, "shares": shares,
        "event_date": _date(_first(root, {"dateOfEvent", "eventDate", "eventDateRequiresFilingThisStatement",
                                          "signatureDate", "dateOfReport"})),
    }
