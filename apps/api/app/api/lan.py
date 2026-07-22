"""LAN 서버 모니터링 — 원본 lan-dashboard(Express)의 FastAPI 이식.

원본과 동일한 동작:
· TCP 프로빙: connect 성공 = online (asyncio.open_connection, 5s 타임아웃).
· HTTP 프로빙: GET http://host:port/ 응답코드 < 500 = online (httpx, 5s).
  protocol 이 http/https 든 항상 평문 http 로 쏜다(원본 그대로, 2026-07-21 결정).
· 서버 목록/그룹은 JSON 파일(STORAGE_DIR/lan_dashboard.json)에 저장.
· 상태는 인메모리 캐시에만 존재하고, 백그라운드 태스크가 30초마다 전체 재점검.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas import (
    LanGroupIn,
    LanServerIn,
    LanServerOut,
    LanServerUpdate,
    LanStatusOut,
    LanSummaryOut,
)

router = APIRouter(prefix="/api/v1/lan", tags=["lan"])

CONFIG_PATH = Path(settings.STORAGE_DIR) / "lan_dashboard.json"
CHECK_TIMEOUT = 5.0

# 인메모리 상태 캐시(id -> status dict). 재시작하면 unknown 부터 시작(원본 동일).
_status_cache: dict[str, dict[str, Any]] = {}
# heartbeat: key -> 마지막 수신 epoch(초). 포트 없는 프로세스의 dead-man's-switch.
_heartbeat_seen: dict[str, float] = {}
# 파일 read-modify-write 직렬화용.
_file_lock = asyncio.Lock()

# 최초 실행 시드 — 원본 lan-dashboard/config.json 스냅샷(2026-07-21).
_SEED: dict[str, Any] = {
    "checkIntervalMs": 30000,
    "servers": [
        {"id": "taco", "name": "TACO", "host": "192.168.194.121", "port": 8501, "protocol": "http", "description": "TACO", "group": "Server-P"},
        {"id": "192_168_199_120-4000-1776907079564", "name": "LAN Server Monitor", "host": "192.168.199.120", "port": 4000, "protocol": "http", "description": "", "group": "Developer_PT1"},
        {"id": "192_168_199_120-8002-1776907140735", "name": "펀드 공시 모니터", "host": "192.168.194.121", "port": 8002, "protocol": "http", "description": "", "group": "Server-P"},
        {"id": "192_168_199_120-8765-1776907420711", "name": "종토방 모니터", "host": "192.168.199.120", "port": 8765, "protocol": "http", "description": "", "group": "Developer_PT1"},
        {"id": "192_168_199_120-8002-1776907498233", "name": "AI Model 사용량 모니터", "host": "192.168.199.120", "port": 8002, "protocol": "http", "description": "", "group": "Developer_PT1"},
        {"id": "192_168_194_121-8000-1778021821273", "name": "월초보고서", "host": "192.168.194.121", "port": 8000, "protocol": "http", "description": "", "group": "Server-P"},
        {"id": "192_168_194_121-8100-1779318444202", "name": "ETF Peer 비교 대시보드", "host": "192.168.194.121", "port": 8100, "protocol": "http", "description": "", "group": "Server-P"},
        {"id": "192_168_199_120-8770-1783646167949", "name": "내부자 거래 추적", "host": "192.168.199.120", "port": 8770, "protocol": "tcp", "description": "", "group": "Developer_PT1"},
        {"id": "192_168_199_63-3000-1784180450682", "name": "통합 대시보드", "host": "192.168.199.63", "port": 3000, "protocol": "tcp", "description": "GE_ DASHBOARD", "group": ""},
    ],
    "groups": ["Developer_PT1", "Server-P", "Developer_PT2"],
}


# ── 영속화 ───────────────────────────────────────────────────────────────
def _write_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)  # 원자적 교체 — 리더는 항상 완전한 파일을 본다.


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        config = json.loads(json.dumps(_SEED))  # 시드 딥카피
        _write_config(config)

    config.setdefault("servers", [])
    groups = config.setdefault("groups", [])
    for s in config["servers"]:
        g = s.get("group")
        if g and g not in groups:
            groups.append(g)
    return config


# ── 프로빙 ───────────────────────────────────────────────────────────────
async def _check_tcp(host: str, port: int) -> dict[str, Any]:
    start = time.monotonic()
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=CHECK_TIMEOUT
        )
        return {"status": "online", "responseTime": int((time.monotonic() - start) * 1000)}
    except asyncio.TimeoutError:
        return {"status": "offline", "responseTime": None, "error": "Connection timed out"}
    except Exception as exc:  # noqa: BLE001 — 연결 실패는 전부 offline
        return {"status": "offline", "responseTime": None, "error": str(exc)}
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass


async def _check_http(host: str, port: int) -> dict[str, Any]:
    start = time.monotonic()
    url = f"http://{host}:{port}/"  # protocol 이 https 여도 http 로 쏜다(원본 동일).
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
            resp = await client.get(url)
        return {
            "status": "online" if resp.status_code < 500 else "error",
            "responseTime": int((time.monotonic() - start) * 1000),
            "httpStatus": resp.status_code,
        }
    except httpx.TimeoutException:
        return {"status": "offline", "responseTime": None, "error": "Request timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "offline", "responseTime": None, "error": str(exc)}


def _heartbeat_status(server: dict[str, Any]) -> dict[str, Any]:
    """포트 없는 프로세스: 마지막 POST 수신 age 로 online/offline 판정."""
    seen = _heartbeat_seen.get(server.get("key") or "")
    max_age = server.get("maxAgeSec") or 120
    if seen is None:
        return {
            "status": "unknown",
            "responseTime": None,
            "lastChecked": None,
            "error": "no heartbeat received",
        }
    age = time.time() - seen
    seen_iso = datetime.fromtimestamp(seen, timezone.utc).isoformat()
    if age <= max_age:
        return {"status": "online", "responseTime": None, "lastChecked": seen_iso}
    return {
        "status": "offline",
        "responseTime": None,
        "lastChecked": seen_iso,
        "error": f"last heartbeat {int(age)}s ago",
    }


async def _check_server(server: dict[str, Any]) -> dict[str, Any]:
    proto = server.get("protocol")
    if proto == "heartbeat":
        return {**_heartbeat_status(server), "id": server["id"]}
    if proto in ("http", "https"):
        result = await _check_http(server["host"], server["port"])
    else:
        result = await _check_tcp(server["host"], server["port"])
    result["id"] = server["id"]
    result["lastChecked"] = datetime.now(timezone.utc).isoformat()
    return result


async def _check_all() -> None:
    config = _load_config()
    # heartbeat 는 폴링하지 않는다(수신 기반, 읽을 때 실시간 계산).
    targets = [s for s in config["servers"] if s.get("protocol") != "heartbeat"]
    results = await asyncio.gather(
        *(_check_server(s) for s in targets), return_exceptions=True
    )
    for r in results:
        if isinstance(r, dict):
            _status_cache[r["id"]] = r


async def background_checker_loop() -> None:
    """기동 즉시 1회 전체 점검 후 checkIntervalMs 주기로 반복(원본 setInterval 대응)."""
    while True:
        interval = 30.0
        try:
            await _check_all()
            interval = _load_config().get("checkIntervalMs", 30000) / 1000
        except Exception:  # noqa: BLE001 — 루프는 절대 죽지 않는다
            pass
        await asyncio.sleep(interval)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────
def _status_for(server: dict[str, Any]) -> dict[str, Any]:
    # heartbeat 는 수신 age 가 매초 변하므로 읽을 때 실시간 계산, 나머지는 캐시.
    if server.get("protocol") == "heartbeat":
        return _heartbeat_status(server)
    return _status_cache.get(server["id"]) or {"status": "unknown", "lastChecked": None}


def _with_status(server: dict[str, Any]) -> dict[str, Any]:
    return {**server, "status": _status_for(server)}


def _find_index(config: dict[str, Any], server_id: str) -> int:
    return next(
        (i for i, s in enumerate(config["servers"]) if s["id"] == server_id), -1
    )


# ── 라우트 (원본 9개 그대로) ─────────────────────────────────────────────
@router.get("/servers", response_model=list[LanServerOut])
async def list_servers() -> list[dict[str, Any]]:
    return [_with_status(s) for s in _load_config()["servers"]]


@router.post("/servers", response_model=LanServerOut, status_code=201)
async def add_server(body: LanServerIn) -> dict[str, Any]:
    proto = body.protocol or "tcp"
    if proto == "heartbeat":
        if not body.key:
            raise HTTPException(status_code=400, detail="key is required for heartbeat")
    elif not body.host or not body.port:
        raise HTTPException(status_code=400, detail="host and port are required")

    anchor = body.host or body.key or "hb"
    server = {
        "id": f"{anchor}-{body.port}-{int(time.time() * 1000)}".replace(".", "_"),
        "name": body.name,
        "host": body.host,
        "port": body.port,
        "protocol": proto,
        "description": body.description or "",
        "group": body.group or "",
        "key": body.key or "",
        "maxAgeSec": body.maxAgeSec,
    }
    async with _file_lock:
        config = _load_config()
        config["servers"].append(server)
        if server["group"] and server["group"] not in config["groups"]:
            config["groups"].append(server["group"])
        _write_config(config)

    # 추가 즉시 1회 점검(heartbeat 는 수신 대기이므로 제외).
    if proto != "heartbeat":
        _status_cache[server["id"]] = await _check_server(server)
    return _with_status(server)


@router.put("/servers/{server_id}", response_model=LanServerOut)
async def update_server(server_id: str, body: LanServerUpdate) -> dict[str, Any]:
    async with _file_lock:
        config = _load_config()
        idx = _find_index(config, server_id)
        if idx == -1:
            raise HTTPException(status_code=404, detail="Server not found")
        server = config["servers"][idx]
        for key, value in body.model_dump(exclude_unset=True).items():
            if value is not None:
                server[key] = value
        if server.get("group") and server["group"] not in config["groups"]:
            config["groups"].append(server["group"])
        config["servers"][idx] = server
        _write_config(config)
    return _with_status(server)


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str) -> dict[str, Any]:
    async with _file_lock:
        config = _load_config()
        idx = _find_index(config, server_id)
        if idx == -1:
            raise HTTPException(status_code=404, detail="Server not found")
        config["servers"].pop(idx)
        _write_config(config)
    _status_cache.pop(server_id, None)
    return {"ok": True}


@router.post("/check")
async def check_all_now() -> dict[str, Any]:
    await _check_all()
    return {"ok": True, "checkedAt": datetime.now(timezone.utc).isoformat()}


@router.post("/check/{server_id}", response_model=LanStatusOut)
async def check_one_now(server_id: str) -> dict[str, Any]:
    config = _load_config()
    server = next((s for s in config["servers"] if s["id"] == server_id), None)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    result = await _check_server(server)
    _status_cache[server_id] = result
    return result


@router.post("/heartbeat/{key}")
async def heartbeat(key: str) -> dict[str, Any]:
    """포트 없는 프로세스가 살아있음을 알리는 push(각 루프 tick마다 호출)."""
    _heartbeat_seen[key] = time.time()
    return {"ok": True, "key": key, "at": datetime.now(timezone.utc).isoformat()}


@router.get("/groups", response_model=list[str])
async def list_groups() -> list[str]:
    return _load_config()["groups"]


@router.post("/groups", status_code=201)
async def add_group(body: LanGroupIn) -> dict[str, str]:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    async with _file_lock:
        config = _load_config()
        if name in config["groups"]:
            raise HTTPException(status_code=409, detail="Group already exists")
        config["groups"].append(name)
        _write_config(config)
    return {"name": name}


@router.get("/summary", response_model=LanSummaryOut)
async def summary() -> LanSummaryOut:
    config = _load_config()
    online = offline = unknown = 0
    for s in config["servers"]:
        st = _status_for(s)["status"]
        if st == "online":
            online += 1
        elif st in ("offline", "error"):
            offline += 1
        else:
            unknown += 1
    return LanSummaryOut(
        total=len(config["servers"]), online=online, offline=offline, unknown=unknown
    )
