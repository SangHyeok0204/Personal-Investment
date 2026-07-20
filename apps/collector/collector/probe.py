"""Phase-0 게이트 프로브 — 컨테이너 안에서 실행.

1) TLS verify 매트릭스: 런타임 HTTPS 대상 4곳을 verify=ON(기본, 시스템 CA 번들)으로
   호출해 Somansa MITM 하에서 인증서 검증이 통과하는지 확인한다.
   HTTP 상태코드는 무엇이든 무방 — TLS 핸드셰이크 성공 여부만 게이트다.
   KIS WS(ops.koreainvestment.com:21000)는 평문 ws:// 라 TLS 무관 → TCP 도달성만 본다.

2) --krx: KRX 로그인 프로브(정보성). batch.py의 로그인 플로우를 그대로 재현해
   _error_code를 기록한다 (CD001=성공, CD011=중복세션→skipDup 재시도, CD005=IP 미허용).
   자격증명은 env(ETF_INAV_MONITOR__KRX_USER/PW)에서 읽고 절대 출력하지 않는다.

사용:
    docker compose --profile collector run --rm collector python -m collector.probe
    docker compose --profile collector run --rm collector python -m collector.probe --krx
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys

import requests

TLS_MATRIX = [
    ("KIS_REST", "https://openapi.koreainvestment.com:9443/"),
    ("NAVER_FX", "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"),
    ("TWSE", "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"),
    ("KRX", "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"),
]
KIS_WS_HOST, KIS_WS_PORT = "ops.koreainvestment.com", 21000

# KRX 로그인 상수 — 구시스템 batch.py와 동일.
KRX_LOGIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
KRX_LOGIN_JSP_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
KRX_LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
KRX_MAIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"
KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
}


def tls_matrix() -> list[dict]:
    results = []
    for name, url in TLS_MATRIX:
        row = {"name": name, "url": url}
        try:
            r = requests.get(url, timeout=15)  # verify=True 기본 (시스템 번들)
            row["tls"] = "OK"
            row["http_status"] = r.status_code
        except requests.exceptions.SSLError as e:
            row["tls"] = "FAIL"
            row["error"] = str(e)[:300]
        except Exception as e:  # DNS/타임아웃 등 — TLS 판정과 구분해 기록
            row["tls"] = "OTHER"
            row["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        results.append(row)

    row = {"name": "KIS_WS_TCP", "url": f"tcp://{KIS_WS_HOST}:{KIS_WS_PORT} (평문 ws://, TLS 무관)"}
    try:
        with socket.create_connection((KIS_WS_HOST, KIS_WS_PORT), timeout=10):
            row["tls"] = "N/A"
            row["tcp"] = "OK"
    except Exception as e:
        row["tls"] = "N/A"
        row["tcp"] = f"FAIL {type(e).__name__}: {str(e)[:200]}"
    results.append(row)
    return results


def krx_login_probe() -> dict:
    user = os.environ.get("ETF_INAV_MONITOR__KRX_USER", "")
    pw = os.environ.get("ETF_INAV_MONITOR__KRX_PW", "")
    if not user or not pw:
        return {"probe": "KRX_LOGIN", "result": "SKIP", "reason": "credentials not in env"}

    s = requests.Session()
    try:
        s.get(KRX_MAIN_PAGE_URL, headers=KRX_HEADERS, timeout=15)
        s.get(KRX_LOGIN_PAGE_URL, headers=KRX_HEADERS, timeout=15)
        s.get(KRX_LOGIN_JSP_URL, headers={**KRX_HEADERS, "Referer": KRX_LOGIN_PAGE_URL}, timeout=15)
        headers = {**KRX_HEADERS, "Referer": KRX_LOGIN_PAGE_URL, "X-Requested-With": "XMLHttpRequest"}
        payload = {"mbrId": user, "pw": pw, "mbrNm": "", "telNo": "", "di": "", "certType": ""}
        r = s.post(KRX_LOGIN_URL, headers=headers, data=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        code = data.get("_error_code", "")
        if code == "CD011":  # 중복 세션 → skipDup 재시도 (구시스템과 동일)
            payload["skipDup"] = "Y"
            r = s.post(KRX_LOGIN_URL, headers=headers, data=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            code = data.get("_error_code", "")
        ok = (not code) or code == "CD001"
        return {
            "probe": "KRX_LOGIN",
            "result": "OK" if ok else "FAIL",
            "error_code": code or "CD001",
            "message": str(data.get("_error_message", ""))[:200],
        }
    except Exception as e:
        return {"probe": "KRX_LOGIN", "result": "ERROR", "error": f"{type(e).__name__}: {str(e)[:300]}"}
    finally:
        s.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--krx", action="store_true", help="KRX 로그인 프로브 포함 (정보성)")
    args = ap.parse_args()

    out = {"tls_matrix": tls_matrix()}
    if args.krx:
        out["krx_login"] = krx_login_probe()
    print(json.dumps(out, ensure_ascii=False, indent=2))

    tls_fail = [r for r in out["tls_matrix"] if r.get("tls") == "FAIL"]
    sys.exit(1 if tls_fail else 0)


if __name__ == "__main__":
    main()
