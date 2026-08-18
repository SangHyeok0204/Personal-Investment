"""[뉴스 모니터링 · 텔레그램] 카드 피드 — 상류 집계 JSON 리더 (2026-08-12).

카드의 내용과 '언급 n건'은 전부 상류(S: Telegram_Bot)가 만든다. 이 모듈은
`output/dashboard_analysis.json` 을 읽어 대시보드 계약에 맞춰 내주기만 한다.

왜 여기서 계산하지 않는가
  - 산정 방식을 일간 HTML 리포트와 **똑같이** 가져가기로 했다(사용자 확정). 그 방식은
    Opus 가 24h 토픽을 의미 단위로 묶고 mentions 를 매기는 것인데, 이 컨테이너에는
    claude 가 없고 인증도 구독 OAuth 라 옮길 수 없다. 그래서 S: 쪽이 굽고 여기는
    읽는다 — 성과보고(perf_brief)와 같은 구조다.
  - 직전까지는 여기서 문장 토큰 자카드로 직접 묶었는데 층위가 달라 숫자가 어긋났다
    (2026-08-12 실측): 같은 주제라도 문장이 다르면 안 묶여 AI메모리 174글이 138개
    카드로 흩어졌고(클러스터 91%가 1건짜리), 반대로 방 고정 양식이 같으면 남남을
    묶어 '[시그널랩 실적속보]' 20개 회사가 한 장(20건)이 됐다. 문장 유사도는 내용이
    아니라 서식을 재고 있었다.

풀링은 2시간 간격 KST (상류 collect.py --watch, 00·02·…·22 슬롯). 그 시각을 지나도
파일이 갱신돼 있지 않으면 stale 로 표시해 화면이 조용히 옛 집계를 보여주지 않게 한다.
이 표시가 실제로 필요했다: 2026-08-14 에 상류 --watch 가 옛 스케줄을 모듈 캐시로 물고
있어 집계가 이틀 묵었는데, 그동안 화면은 아무 말 없이 8/12 카드를 보여주고 있었다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

ANALYSIS_PATH = os.environ.get(
    "TELEGRAM_ANALYSIS_PATH", "/srv/legacy/telegram/output/dashboard_analysis.json"
)

# 일간 리포트와 같은 3열. 열마다 상위 3 + 단독·특이 2 = 5장이라 5×3 격자가 딱 찬다.
SECTIONS = [
    ("macro", "매크로", "🌐"),
    ("industry", "산업", "🏭"),
    ("stock", "종목", "🏷️"),
]
# 상류 스케줄 = 2시간 간격 정각 슬롯(00,02,...,22). 이 시각이 지났는데 집계가
# 그 전 것이면 풀링이 빠진 것이다. 상류 collect.POOL_INTERVAL_H 와 짝이다.
POOL_INTERVAL_H = 2
POOL_MINUTES = tuple(h * 60 for h in range(0, 24, POOL_INTERVAL_H))
# 풀링 자체가 Opus 1콜이라 오래 걸린다 — 그만큼은 늦어도 정상으로 본다.
# 07:30 리포트는 실측 80분까지 걸렸다(2026-08-14: 07:30 시작 → 08:51 저장).
POOL_GRACE_MIN = 90

_SPLIT_RE = re.compile(r"\s*·\s*")
MAX_CHIPS = 6


def _log(msg: str) -> None:
    import sys

    print(f"[collector] telegram-news: {msg}", file=sys.stderr, flush=True)


def _expected_pool(now: datetime) -> datetime:
    """now 기준 '직전에 돌았어야 할' 풀링 시각."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    slots = [today + timedelta(minutes=m) for m in POOL_MINUTES]
    past = [s for s in slots if s <= now]
    if past:
        return past[-1]
    return slots[-1] - timedelta(days=1)  # 오늘 첫 풀링 전이면 어제 마지막 것


def _card(key: str, issue: dict, notable: bool) -> dict:
    title = (issue.get("title") or "").strip()
    summary = issue.get("summary") or ""
    chips = [c.strip() for c in _SPLIT_RE.split(summary) if c.strip()][:MAX_CHIPS]
    mentions = issue.get("mentions")
    return {
        # 제목 해시 = 카드 정체성. 풀링에서 제목이 그대로면 같은 카드로 남아
        # 재등장 애니메이션이 헛돌지 않는다.
        "id": f"{key}-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:10]}",
        "title": title,
        "chips": chips,
        "mentions": mentions if isinstance(mentions, int) and mentions > 0 else None,
        "notable": notable,
    }


class TelegramNews:
    """집계 JSON 을 mtime 기준으로 읽어 payload 로 들고 있는다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: dict | None = None
        self._etag = ""
        self._mtime = -1.0

    def available(self) -> bool:
        return os.path.isdir(os.path.dirname(ANALYSIS_PATH))

    def refresh(self) -> None:
        """디스크 판독(SMB). 백그라운드 루프에서만 호출한다.

        파일이 안 바뀌었어도 payload 는 다시 만든다 — stale 판정이 시각에 의존해서
        (풀링 시각을 지나는 순간 stale 이 서야 한다) 파일 mtime 만으로는 못 잡는다.
        JSON 재파싱만 mtime 으로 건너뛴다.
        """
        now = datetime.now(KST)
        try:
            mtime = os.path.getmtime(ANALYSIS_PATH)
        except OSError:
            self._store(self._empty(now, missing=True))
            return
        if mtime != self._mtime:
            try:
                with open(ANALYSIS_PATH, encoding="utf-8") as f:
                    self._raw = json.load(f)
                self._mtime = mtime
            except (OSError, ValueError) as exc:
                _log(f"집계 JSON 읽기 실패: {exc!r}")
                if getattr(self, "_raw", None) is None:
                    self._store(self._empty(now, missing=True))
                    return
        self._store(self._build(self._raw, now))

    # -- payload --
    def _empty(self, now: datetime, missing: bool) -> dict:
        return {
            "generatedAt": "",
            "readAt": now.isoformat(),
            "available": not missing,
            "stale": True,
            "expectedAt": _expected_pool(now).isoformat(),
            "poolTimes": [f"{m // 60:02d}:{m % 60:02d}" for m in POOL_MINUTES],
            "windowHours": 24,
            "windowStart": "",
            "windowEnd": "",
            "topics": 0,
            "rooms": 0,
            "analysisPath": ANALYSIS_PATH,
            "categories": [
                {"key": k, "label": l, "icon": i, "cards": []} for k, l, i in SECTIONS
            ],
        }

    def _build(self, raw: dict, now: datetime) -> dict:
        expected = _expected_pool(now)
        gen_s = raw.get("generatedAt") or ""
        try:
            gen = datetime.fromisoformat(gen_s)
        except ValueError:
            gen = None
        # 예정 시각을 유예시간 넘겨 지났는데 집계가 그보다 앞서면 풀링이 빠진 것.
        stale = bool(
            gen is None
            or (gen < expected and (now - expected) > timedelta(minutes=POOL_GRACE_MIN))
        )
        sections = raw.get("sections") or {}
        cats = []
        for key, label, icon in SECTIONS:
            sec = sections.get(key) or {}
            cards = [_card(key, i, False) for i in (sec.get("top") or [])[:3]]
            cards += [_card(key, i, True) for i in (sec.get("notable") or [])[:2]]
            cats.append({"key": key, "label": label, "icon": icon, "cards": cards})
        return {
            "generatedAt": gen_s,
            "readAt": now.isoformat(),
            "available": True,
            "stale": stale,
            "expectedAt": expected.isoformat(),
            "poolTimes": [f"{m // 60:02d}:{m % 60:02d}" for m in POOL_MINUTES],
            "windowHours": raw.get("windowHours") or 24,
            "windowStart": raw.get("windowStart") or "",
            "windowEnd": raw.get("windowEnd") or "",
            "topics": raw.get("topics") or 0,
            "rooms": raw.get("rooms") or 0,
            "analysisPath": ANALYSIS_PATH,
            "categories": cats,
        }

    def _store(self, payload: dict) -> None:
        body = dict(payload)
        body.pop("readAt")
        etag = '"tg-' + hashlib.sha1(
            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16] + '"'
        with self._lock:
            self._payload = payload
            self._etag = etag

    def serve(self) -> tuple[dict | None, str]:
        with self._lock:
            return self._payload, self._etag


_INSTANCE: TelegramNews | None = None


def instance() -> TelegramNews:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = TelegramNews()
    return _INSTANCE
