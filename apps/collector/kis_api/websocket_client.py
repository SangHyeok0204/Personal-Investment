from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Iterable

import websockets

from kis_api.auth import KisAuth


HDFSCNT0_TR_ID = "HDFSCNT0"
HDFSCNT0_COLUMNS = [
    "SYMB", "ZDIV", "TYMD", "XYMD", "XHMS", "KYMD", "KHMS",
    "OPEN", "HIGH", "LOW", "LAST", "SIGN", "DIFF", "RATE",
    "PBID", "PASK", "VBID", "VASK", "EVOL", "TVOL", "TAMT",
    "BIVL", "ASVL", "STRN", "MTYP",
]

MAX_SUBSCRIPTIONS = 40
SUBSCRIBE_TYPE = "1"
UNSUBSCRIBE_TYPE = "2"

# tr_key prefix: 'D' for delayed (free) US realtime ccnl.
# Format: D{EXCH3}{SYMBOL}, e.g. DNASAAPL, DNYSNVDA, DAMSARKK.
TR_KEY_PREFIX_DELAYED = "D"
EXCHANGE_TO_TRKEY = {
    "NAS": "NAS",
    "NYS": "NYS",
    "AMS": "AMS",
    "HKS": "HKS",
    "SHS": "SHS",
    "SZS": "SZS",
    "TSE": "TSE",
}


def build_tr_key(exchange: str, symbol: str, prefix: str = TR_KEY_PREFIX_DELAYED) -> str:
    exch = EXCHANGE_TO_TRKEY.get(exchange.upper())
    if not exch:
        raise ValueError(f"Unsupported exchange for tr_key: {exchange}")
    return f"{prefix}{exch}{symbol.upper()}"


def parse_tr_key(tr_key: str) -> tuple[str, str]:
    """Inverse of build_tr_key. Returns (exchange_kis_code, symbol)."""
    if not tr_key or len(tr_key) < 5:
        raise ValueError(f"Invalid tr_key: {tr_key}")
    exch_segment = tr_key[1:4]
    return exch_segment.upper(), tr_key[4:].upper()


@dataclass
class TickEvent:
    exchange: str
    symbol: str
    last: float | None
    fields: dict
    raw: str
    received_at: str = field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))


def _to_float(value: str) -> float | None:
    if value in (None, "", "0"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def parse_hdfscnt0_message(raw: str) -> list[TickEvent]:
    """Parse a raw '0|HDFSCNT0|N|payload' frame.

    Each frame can carry multiple ticks (count = field 3). The payload is a
    caret-delimited CSV; 25 columns per tick concatenated.
    """
    parts = raw.split("|", 3)
    if len(parts) < 4 or parts[1] != HDFSCNT0_TR_ID:
        return []

    try:
        count = int(parts[2])
    except (TypeError, ValueError):
        count = 1

    fields = parts[3].split("^")
    col_count = len(HDFSCNT0_COLUMNS)
    events: list[TickEvent] = []
    for tick_idx in range(count):
        offset = tick_idx * col_count
        chunk = fields[offset : offset + col_count]
        if len(chunk) < col_count:
            break
        row = dict(zip(HDFSCNT0_COLUMNS, chunk))
        symbol = row.get("SYMB", "").upper()
        last = _to_float(row.get("LAST"))
        events.append(
            TickEvent(
                exchange="",  # filled by caller from subscription map
                symbol=symbol,
                last=last,
                fields=row,
                raw=raw,
            )
        )
    return events


class KisWebSocket:
    """Async client for KIS overseas realtime-delayed price WebSocket.

    Usage:
        ws = KisWebSocket(auth)
        await ws.connect()
        await ws.subscribe([("NAS", "AAPL"), ("NYS", "NVDA")])
        async for event in ws.events():
            print(event)
    """

    def __init__(
        self,
        auth: KisAuth,
        tr_id: str = HDFSCNT0_TR_ID,
        on_pingpong: Callable[[str], Awaitable[None]] | None = None,
    ):
        self.auth = auth
        self.tr_id = tr_id
        self._connection: websockets.WebSocketClientProtocol | None = None
        self._approval_key: str | None = None
        self._subscriptions: dict[str, tuple[str, str]] = {}
        self._on_pingpong = on_pingpong

    async def connect(self) -> None:
        if self._connection is not None:
            return
        self._approval_key = self.auth.approval_key()
        # KIS uses a JSON 'PINGPONG' message for keepalive (handled in events()),
        # and does not respond to standard ws control-frame pings. Disable the
        # websockets library's auto-ping to avoid false-positive 1011 timeouts.
        self._connection = await websockets.connect(
            self.auth.credentials.ws_url,
            ping_interval=None,
        )

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def _send(self, tr_type: str, tr_key: str) -> None:
        if self._connection is None or self._approval_key is None:
            raise RuntimeError("WebSocket is not connected. Call connect() first.")
        message = {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": tr_type,
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": self.tr_id,
                    "tr_key": tr_key,
                }
            },
        }
        await self._connection.send(json.dumps(message))

    async def subscribe(self, pairs: Iterable[tuple[str, str]]) -> list[str]:
        new_keys: list[str] = []
        for exchange, symbol in pairs:
            tr_key = build_tr_key(exchange, symbol)
            if tr_key in self._subscriptions:
                continue
            if len(self._subscriptions) >= MAX_SUBSCRIPTIONS:
                raise RuntimeError(
                    f"Subscription limit reached ({MAX_SUBSCRIPTIONS}). "
                    "Use batch rotation or unsubscribe first."
                )
            await self._send(SUBSCRIBE_TYPE, tr_key)
            self._subscriptions[tr_key] = (exchange.upper(), symbol.upper())
            new_keys.append(tr_key)
        return new_keys

    async def unsubscribe(self, pairs: Iterable[tuple[str, str]]) -> list[str]:
        removed: list[str] = []
        for exchange, symbol in pairs:
            tr_key = build_tr_key(exchange, symbol)
            if tr_key not in self._subscriptions:
                continue
            try:
                await self._send(UNSUBSCRIBE_TYPE, tr_key)
            finally:
                # Release the local slot even if the send fails, so a transient
                # connection error does not exhaust MAX_SUBSCRIPTIONS.
                self._subscriptions.pop(tr_key, None)
            removed.append(tr_key)
        return removed

    async def unsubscribe_all(self) -> None:
        pairs = list(self._subscriptions.values())
        for exchange, symbol in pairs:
            await self.unsubscribe([(exchange, symbol)])

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)

    async def events(self):
        if self._connection is None:
            raise RuntimeError("WebSocket is not connected. Call connect() first.")
        async for raw in self._connection:
            if not isinstance(raw, str) or not raw:
                continue

            if raw.startswith("{"):
                # JSON control frame: subscribe ack, ping/pong, etc.
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                tr_id = (
                    payload.get("header", {}).get("tr_id")
                    or payload.get("body", {}).get("rt_cd")
                )
                if tr_id == "PINGPONG":
                    if self._on_pingpong:
                        await self._on_pingpong(raw)
                    else:
                        await self._connection.send(raw)
                continue

            if raw[0] not in ("0", "1"):
                continue
            head = raw.split("|", 3)
            if len(head) < 4 or head[1] != self.tr_id:
                continue

            symbol_to_exchange = {sym: exch for exch, sym in self._subscriptions.values()}
            for event in parse_hdfscnt0_message(raw):
                exchange = symbol_to_exchange.get(event.symbol)
                if exchange is None:
                    continue
                yield TickEvent(
                    exchange=exchange,
                    symbol=event.symbol,
                    last=event.last,
                    fields=event.fields,
                    raw=event.raw,
                    received_at=event.received_at,
                )
