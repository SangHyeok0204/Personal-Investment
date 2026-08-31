"""[ETF 순매수 모니터] — CHECK 호가 envelope 의 ``newEtfs`` 판독 (2026-08-25).

CHECK 에이전트가 매초 POST 하는 호가 envelope(`/internal/check/hoga` → collector
`/ingest/hoga`)의 payload 에 관심 ETF(주로 신규상장) 수급이 ``newEtfs`` 배열로
같이 실려 온다 — CHECK 시트에 행을 추가하면 자동 포함. 여기서 그 배열을
[종목 모니터] 우상단 카드 payload 로 접는다.

★같은 날 첫 설계는 S: 의 ETF_FLOW_MONITOR.db 브리지였으나(당시 안내.md 계약),
  CHECK 쪽이 기존 호가 lane 에 태우는 것으로 구현해 소비측 배선을 이쪽으로
  바꿨다 — DB 브리지·SMB 복사 코드는 만들지/남기지 않았다. 계약 정본은
  시장모니터 폴더의 ETF_FLOW_MONITOR_DB_안내.md(개편본).

단위 변환이 이 모듈의 존재 이유다: 피드의 tradeAmt·indivNet 는 **억원**,
웹 포맷터(fmtWon)는 **원** 기준이라 ×1e8 로 환산해 내보낸다. volume 은 주 그대로.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))


def _eok_to_won(v) -> float | None:
    """억원 → 원. 숫자가 아니면 None (fail-soft — 행 하나 때문에 카드를 비우지 않는다)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) * 1e8
    return None


def _num(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def build_etf_flows(hoga: dict | None) -> dict:
    """state.hoga() 리더 결과 → 카드 payload.

    반환::

        { "generated_at": "YYYY-MM-DD HH:MM:SS",   # KST
          "asof": envelope source_timestamp | None,
          "rows": [ { "code","name","listing_date","trade_value","trade_volume",
                      "indiv_net_buy","trade_date","observed_at" }, ... ] }

    정렬은 CHECK 시트 순서(`no` 오름차순) — 관심 목록의 큐레이션 순서를 그대로 둔다.
    envelope 미수신(기동 직후)·newEtfs 부재면 rows 빈 배열(화면이 대기 문구).
    """
    now = datetime.now(_KST)
    out: dict = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "asof": None,
        "rows": [],
    }
    if not hoga:
        return out
    payload = hoga.get("payload") or {}
    etfs = payload.get("newEtfs")
    if not isinstance(etfs, list) or not etfs:
        return out

    asof = hoga.get("source_timestamp")
    out["asof"] = asof

    def _order(e: dict):
        no = e.get("no")
        return (0, no) if isinstance(no, (int, float)) else (1, 0)

    for e in sorted((e for e in etfs if isinstance(e, dict)), key=_order):
        code = e.get("code")
        if not code:
            continue
        out["rows"].append({
            "code": str(code),
            "name": e.get("name"),
            "listing_date": e.get("listedDate"),
            "trade_value": _eok_to_won(e.get("tradeAmt")),
            "trade_volume": _num(e.get("volume")),
            "indiv_net_buy": _eok_to_won(e.get("indivNet")),
            # vol3tick = LP기반 추정 개인 순매수(억원) — 사용자 확정 2026-08-25.
            # 이름이 volume 처럼 생겼지만 금액이다. 필드 부재(과거 envelope)면 None.
            "indiv_net_lp_est": _eok_to_won(e.get("vol3tick")),
            "trade_date": None,  # 피드에 없음 — envelope 자체가 당일 실시간이다
            "observed_at": asof,
        })
    return out
