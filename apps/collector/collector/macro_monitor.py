"""매크로 패널 판독 — 매크로모니터가 구운 macro_panels.json 서빙 (2026-08-13).

S: 의 매크로모니터가 FRED/BLS/CME 를 macro.db(SQLite)에 적재하고, 리포트를 만들 때
`macro_panels.py --export` 로 계산 결과를 JSON 한 장으로 굽는다. collector 는 그 JSON
만 읽는다.

왜 DB 를 안 읽나 — macro.db 는 CPI/PPI 세부품목까지 담아 300MB 에 가깝다. INDEX_MONITOR
처럼 통째로 .cache 에 복사하는 방식은 SMB 읽기 비용이 감당이 안 된다. 수치 소유는 S:
쪽에 두고 대시보드는 결과만 받는 배선(성과보고 JSON·펀드 시계열 JSON 과 동일)이 맞다.

순수 판독 — 파일이 없거나 깨졌으면 None(→ 503 not ready). mtime 이 바뀔 때만 다시 읽는다.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

SRC = Path(os.environ.get(
    "MACRO_PANELS_PATH", "/srv/legacy/macro/output/macro_panels.json"))

_lock = threading.Lock()
_cache: dict = {"mtime": None, "size": None, "payload": None}


def _log(msg: str) -> None:
    print(f"[macro] {msg}", file=sys.stderr, flush=True)


def panels() -> dict | None:
    """{prices, labor, liquidity, fomc, asof, generatedAt} — 없으면 None.

    JSON 이 10KB 수준이라 mtime 이 바뀌면 그 자리에서 다시 읽어도 부담이 없다
    (index_window 처럼 백그라운드 복사를 둘 이유가 없다)."""
    try:
        st = SRC.stat()
    except OSError:
        return _cache["payload"]          # 마운트가 잠깐 끊겨도 직전 값으로 버틴다
    with _lock:
        if _cache["mtime"] == st.st_mtime_ns and _cache["size"] == st.st_size:
            return _cache["payload"]
        try:
            payload = json.loads(SRC.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log(f"read failed: {exc!r}")
            return _cache["payload"]
        _cache.update(mtime=st.st_mtime_ns, size=st.st_size, payload=payload)
        _log(f"loaded asof={payload.get('asof')} generatedAt={payload.get('generatedAt')}")
        return payload


def etag() -> str:
    """파일 identity 기반 ETag — 내용이 같으면 브라우저가 304 로 끝낸다."""
    return f'W/"macro-{_cache.get("mtime")}-{_cache.get("size")}"'
