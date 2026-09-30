"""거장 13F — 한 분기의 '유효한' 공시 묶음 고르기 (계획 A2 · A5 공용).

⚠️원본(`guru_queries._LATEST_13F_CTE`)은 (기관, 분기)마다 **가장 늦게 낸 공시 하나**만 남겼다.
  13F-HR/A 에는 두 종류가 있다:
    - RESTATEMENT  — 보고서 전체를 다시 냄 → 앞의 것을 **대체**
    - NEW HOLDINGS — 비밀유지(confidential treatment)로 늦게 공개한 **추가분** → 앞의 것에 **더함**
  "가장 늦은 하나" 규칙이면 추가분 1종목짜리 공시가 이겨서, 실측 버크셔 2023Q3 이 152종목 →
  **1종목·비중 100%** 가 됐다. 그런 (기관, 분기) 묶음이 74개였다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Filing13F:
    accession: str
    filing_date: date
    form: str                    # '13F-HR' | '13F-HR/A'
    amendment_type: str | None   # 'RESTATEMENT' | 'NEW HOLDINGS' | None


def effective_accessions(filings: list[Filing13F]) -> tuple[list[str], list[str]]:
    """한 (기관, 분기)의 공시들 → (유효 접수번호들, 품질 경고들).

    제출일 순서로 훑는다: 원본·RESTATEMENT 는 지금까지를 **갈아치우고**, NEW HOLDINGS 는 **더한다**.
    정정 종류를 모르는 /A 는 보수적으로 대체로 본다(추가분을 대체로 보면 종목이 줄 뿐 부풀지는 않는다)
    — 그리고 경고를 남긴다(백필 뒤엔 없어야 한다).
    """
    current: list[str] = []
    warnings: list[str] = []
    for f in sorted(filings, key=lambda x: (x.filing_date, x.accession)):
        is_amend = f.form.upper().endswith("/A")
        if not is_amend or f.amendment_type == "RESTATEMENT":
            current = [f.accession]
        elif f.amendment_type == "NEW HOLDINGS":
            if not current:
                warnings.append(f"{f.accession}: 원본 없이 추가분만 있음")
            current.append(f.accession)
        else:
            warnings.append(f"{f.accession}: 정정 종류 모름 — 대체로 처리")
            current = [f.accession]
    return current, warnings
