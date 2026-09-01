"""[종목 모니터링 · 미국] 이슈 모니터 — 어닝모니터 stock_issue_alert 산출물 판독 (2026-09-01).

상류(S: 어닝모니터 daily-server)가 **KST 06:00 하루 한 번** 돌린다: ChartExchange 에서
Reddit 버즈 급등 종목을 걸러(시총 tier 별 임계) yfinance 로 주가를 붙이고, claude CLI 가
종목마다 핵심 이슈·구조적 영향·투자 시사점 세 줄과 이슈 사유 태그·근거 출처를 만든다.
결과는 `{YYYYMM}/{DD}/` 폴더에 떨어진다. 이 모듈은 그걸 읽어 넘기기만 한다 — 어닝과 같은
"S: 가 굽고 대시보드는 읽는다" 배선이다(컨테이너에 claude 가 없다).

**두 파일을 합쳐 한 장을 만든다.** 어느 쪽도 혼자로는 부족해서다:
  · `analysis_data.json` — 숫자(시총·수익률·버즈 변화·센티먼트)와 기업 설명. 타입이 붙어 있다.
  · `종목이슈분석.md`    — 서사(분석 3줄)·이슈 사유 태그·근거 출처 URL·촉발일. 숫자는 문자열뿐.
숫자를 md 표에서 정규식으로 긁지 않는 이유가 이것이다 — 숫자는 타입이 있는 쪽에서 가져온다.
**md 가 기준(spine)**이고 json 은 티커로 붙인다: 촉발일 필터가 md 에서 종목을 덜어내면
json 도 같이 갱신되지만(main.py:648), 어긋나더라도 화면에 남는 건 리포트에 실린 것뿐이어야 한다.

**날짜 고르기가 이 모듈의 요점이다.** 이 리포트는 매일 나오지 않는다 — 필터를 통과한 종목이
없으면 폴더에 "통과한 종목이 없습니다" txt 한 줄만 남는다(2026-08-27~31 닷새 연속 그랬다).
그래서 '오늘 것'만 보여주면 카드가 며칠씩 빈 채로 있게 된다. 대신 **내용이 있는 가장 최근
리포트**를 띄우고, 오늘 상태(`todayStatus`)를 따로 실어 화면이 며칠 전 것임을 밝히게 한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

ROOT = os.environ.get("STOCK_ISSUE_DIR", "/srv/legacy/stock_issue")
DATA_NAME = "analysis_data.json"
MD_NAME = "종목이슈분석.md"
EMPTY_NAME = "종목이슈분석.txt"

# 이보다 오래된 리포트는 띄우지 않는다. 한 달 지난 버즈는 이슈가 아니라 기록이다.
LOOKBACK_DAYS = 30
# 폴더 훑기 상한 — 위 창을 다 뒤져도 못 찾으면 멈춘다(SMB 왕복이 무한히 늘지 않게).
MAX_PROBE_DAYS = 40

# md 파싱 — 상류 프롬프트가 형식을 못 박아 둬서(main.py:199-224) 정규식으로 충분하다.
_HEAD_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*\(([A-Z0-9.\-]+)\)\s*$")
_TRIGGER_RE = re.compile(r"^<!--\s*촉발일:\s*(.+?)\s*-->$")
_CELL_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")
_BULLET_RE = re.compile(r"^>\s*-\s*(핵심 이슈|구조적 영향|투자 시사점)\s*:\s*(.+)$")
_META_RE = re.compile(r"^>\s*\*\*(분석 대상|필터 기준)\*\*:\s*(.+)$")

# 분석 3줄 → payload 키. 상류 프롬프트의 라벨과 1:1 이다.
_BULLET_KEY = {"핵심 이슈": "issue", "구조적 영향": "structural", "투자 시사점": "implication"}


def _log(msg: str) -> None:
    print(f"[collector] stock-issue: {msg}", file=sys.stderr, flush=True)


def _s(v) -> str | None:
    if not isinstance(v, str):
        return None
    text = v.strip()
    return text or None


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return None if v != v else float(v)


# ── 날짜 고르기 ────────────────────────────────────────────────────────────
def _day_dir(day: date) -> str:
    return os.path.join(ROOT, day.strftime("%Y%m"), day.strftime("%d"))


def _has_report(day: date) -> bool:
    return os.path.isfile(os.path.join(_day_dir(day), DATA_NAME))


def _latest_report_day(today: date) -> date | None:
    """내용이 있는 가장 최근 리포트 날짜. 없으면 None.

    폴더 트리를 훑지 않고 오늘부터 하루씩 되짚는다 — 하루 한 폴더라 최악이
    MAX_PROBE_DAYS 번의 `isfile` 이고, listdir 로 월 폴더를 여는 것보다 왕복이 적다.
    """
    for back in range(MAX_PROBE_DAYS + 1):
        day = today - timedelta(days=back)
        if (today - day).days > LOOKBACK_DAYS:
            return None
        if _has_report(day):
            return day
    return None


def _today_status(today: date) -> tuple[str, str | None]:
    """오늘 슬롯이 어디까지 왔는가 — ready / empty / pending."""
    if _has_report(today):
        return "ready", None
    empty_path = os.path.join(_day_dir(today), EMPTY_NAME)
    try:
        with open(empty_path, encoding="utf-8") as f:
            return "empty", f.read().strip() or None
    except OSError:
        # 폴더도 파일도 없다 = 아직 안 돌았거나 결과를 못 남겼다.
        return "pending", None


# ── 파싱 ───────────────────────────────────────────────────────────────────
def _parse_md(text: str) -> tuple[dict[str, dict], dict[str, str]]:
    """md → (티커별 서사, 리포트 머리글). 순서 보존을 위해 dict 삽입 순서를 쓴다."""
    stocks: dict[str, dict] = {}
    header: dict[str, str] = {}
    cur: dict | None = None

    for raw in text.splitlines():
        line = raw.strip()

        meta = _META_RE.match(line)
        if meta and cur is None:
            header["target" if meta.group(1) == "분석 대상" else "filter"] = meta.group(2)
            continue

        head = _HEAD_RE.match(line)
        if head:
            cur = {
                "name": head.group(1),
                "triggeredOn": None,
                "tags": [],
                "sourceUrl": None,
                "analysis": {},
            }
            stocks[head.group(2)] = cur
            continue

        if cur is None:
            continue

        trigger = _TRIGGER_RE.match(line)
        if trigger:
            # '미확인' 도 그대로 둔다 — 모델이 날짜를 특정 못 했다는 사실 자체가 정보다.
            cur["triggeredOn"] = trigger.group(1)
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            cur["analysis"][_BULLET_KEY[bullet.group(1)]] = bullet.group(2)
            continue

        cell = _CELL_RE.match(line)
        if cell and not set(cell.group(1)) <= set("-: "):
            key, value = cell.group(1), cell.group(2)
            if key == "이슈 사유":
                cur["tags"] = [t.strip() for t in value.split(",") if t.strip()]
            elif key == "근거 출처":
                # URL 유효성 검사에서 죽은 링크는 비워져 온다(main.py:378).
                cur["sourceUrl"] = value if value.startswith("http") else None
    return stocks, header


def _parse(day: date) -> dict:
    """그 날 리포트 한 장. 실패는 호출자가 직전 판으로 버틴다."""
    folder = _day_dir(day)
    with open(os.path.join(folder, DATA_NAME), encoding="utf-8") as f:
        data = json.load(f)
    numbers = {
        t: s
        for s in (data.get("stocks") or [])
        if isinstance(s, dict) and (t := _s(s.get("ticker")))
    }

    try:
        with open(os.path.join(folder, MD_NAME), encoding="utf-8") as f:
            narrative, header = _parse_md(f.read())
    except OSError:
        # md 가 없으면 숫자만이라도 낸다(그런 날은 못 봤지만 카드가 통째로 죽을 일은 아니다).
        _log(f"{day} md 없음 — 숫자만 표시")
        narrative, header = {}, {}

    # md 가 기준. md 가 통째로 없을 때만 json 순서로 떨어진다.
    tickers = list(narrative) or list(numbers)
    stocks = []
    for ticker in tickers:
        n = numbers.get(ticker) or {}
        m = narrative.get(ticker) or {}
        stocks.append(
            {
                "ticker": ticker,
                "name": _s(n.get("name")) or m.get("name") or ticker,
                "description": _s(n.get("description")),
                "marketCap": _s(n.get("market_cap_str")),
                # ⚠️`cap_tier` 는 싣지 않는다. 라벨이 리포트 머리글의 필터 기준과 한 칸씩
                #   어긋나 있다(2026-08-26 실측: INTU $97.8B→"mid", KO $394.3B→"large",
                #   기준상으로는 각각 large·mega). 어느 쪽이 맞는지는 상류 소관이고,
                #   시가총액 숫자가 이미 있으니 틀린 라벨을 굳이 화면에 옮길 이유가 없다.
                "priceChange": _num(n.get("price_change")),
                "monthlyChange": _num(n.get("monthly_change")),
                "mentionChange": _num(n.get("mention_change")),
                "sentiment": _num(n.get("sentiment")),
                "weekly": bool(n.get("weekly")),
                "triggeredOn": m.get("triggeredOn"),
                "tags": m.get("tags") or [],
                "sourceUrl": m.get("sourceUrl"),
                "analysis": m.get("analysis") or {},
            }
        )
    return {
        "asOf": day.isoformat(),
        "collectedAt": _s(data.get("collected_at")),
        "target": header.get("target"),
        "filter": header.get("filter"),
        "stocks": stocks,
    }


class StockIssue:
    """리포트 폴더를 mtime 기준으로 읽어 payload 로 들고 있는다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: dict | None = None
        self._etag = ""
        self._sig: tuple | None = None  # (day, json mtime_ns, md mtime_ns)
        self._parsed: dict | None = None
        self._mtime = 0.0

    def available(self) -> bool:
        return os.path.isdir(ROOT)

    def refresh(self) -> None:
        """디스크 판독(SMB). 백그라운드 루프에서만 호출한다.

        파일이 그대로여도 payload 는 다시 만든다 — '며칠 전 리포트인가'와 오늘 슬롯 상태가
        시각에 의존해서 파일 mtime 으로는 못 잡는다. 무거운 파싱만 mtime 으로 건너뛴다.
        """
        now = datetime.now(KST)
        today = now.date()
        note: str | None = None

        if not self.available():
            self._store(self._empty(now, today, False, f"리포트 폴더가 없습니다 — {ROOT}"))
            return

        day = _latest_report_day(today)
        if day is None:
            # 읽을 수는 있는데 창 안에 리포트가 없다 — 고장이 아니라 '조용한 날들'이다.
            self._store(self._empty(now, today, True, None))
            return

        folder = _day_dir(day)
        sig = (day, _mtime_ns(os.path.join(folder, DATA_NAME)), _mtime_ns(os.path.join(folder, MD_NAME)))
        if sig != self._sig:
            try:
                self._parsed = _parse(day)
            except Exception as exc:  # noqa: BLE001 - 직전 판으로 버틴다
                _log(f"{day} 리포트 판독 실패: {exc!r}")
                if self._parsed is None:
                    self._store(
                        self._empty(now, today, False, f"{day} 리포트를 읽지 못했습니다.")
                    )
                    return
                note = "리포트 재판독 실패 — 직전 판으로 표시 중"
            else:
                self._sig = sig
                self._mtime = max((m for m in sig[1:] if m), default=0) / 1e9
        self._store(self._build(self._parsed, now, today, note))

    # -- payload --
    def _base(self, now: datetime, today: date) -> dict:
        status, message = _today_status(today) if self.available() else ("pending", None)
        return {
            "readAt": now.isoformat(),
            "today": today.isoformat(),
            "todayStatus": status,
            "todayMessage": message,
            "lookbackDays": LOOKBACK_DAYS,
            "reportDir": ROOT,
        }

    def _empty(
        self, now: datetime, today: date, available: bool, note: str | None
    ) -> dict:
        """리포트가 없는 판. `available` 이 '읽을 수 있었는가'와 '내용이 있었는가'를 가른다 —
        조용한 날들(available=True, stocks=[])과 고장(available=False)은 다른 이야기다."""
        return {
            **self._base(now, today),
            "generatedAt": None,
            "available": available,
            "asOf": None,
            "ageDays": None,
            "collectedAt": None,
            "target": None,
            "filter": None,
            "note": note,
            "stocks": [],
        }

    def _build(self, parsed: dict, now: datetime, today: date, note: str | None) -> dict:
        as_of = date.fromisoformat(parsed["asOf"])
        return {
            **self._base(now, today),
            "generatedAt": datetime.fromtimestamp(self._mtime, KST).isoformat()
            if self._mtime
            else None,
            "available": True,
            "asOf": parsed["asOf"],
            "ageDays": (today - as_of).days,
            "collectedAt": parsed["collectedAt"],
            "target": parsed["target"],
            "filter": parsed["filter"],
            "note": note,
            "stocks": parsed["stocks"],
        }

    def _store(self, payload: dict) -> None:
        body = dict(payload)
        body.pop("readAt", None)
        etag = (
            '"si-'
            + hashlib.sha1(
                json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
            + '"'
        )
        with self._lock:
            self._payload = payload
            self._etag = etag

    def serve(self) -> tuple[dict | None, str]:
        with self._lock:
            return self._payload, self._etag


def _mtime_ns(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


_INSTANCE: StockIssue | None = None


def instance() -> StockIssue:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = StockIssue()
    return _INSTANCE
