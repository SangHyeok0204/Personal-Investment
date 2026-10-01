"""영상 녹음 제목 규칙 — `[youtube_261001_월가아재]` (원천 태그 · YYMMDD · 채널명).

★실측(2026-10-01): 실제 Plaud 제목은 `Youtube_261001_월가아재` 였다 — **대괄호가 없고 Y 가 대문자**.
  그래서 대괄호는 있어도 없어도 받고, 태그는 대소문자를 가리지 않는다.
  - 대괄호형: `]` 까지가 채널, 그 뒤 꼬리 글(메모)은 허용하고 버린다.
  - 맨형: `_` 뒤 끝까지가 채널(공백·한글 포함).
⚠️날짜가 달력에 없는 값(261341 등)이면 규칙에 안 맞는 것으로 본다 — 날짜를 지어내지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_BRACKET = re.compile(r"^\[\s*(youtube)_(\d{6})_([^\]]+)\]", re.I)
_BARE = re.compile(r"^(youtube)_(\d{6})_([^\[\]]+)$", re.I)


@dataclass(frozen=True)
class VideoTitle:
    source_tag: str
    video_date: date
    channel: str


def parse_title(title: str | None) -> VideoTitle | None:
    s = (title or "").strip()
    m = _BRACKET.match(s) or _BARE.match(s)
    if not m:
        return None
    ymd = m.group(2)
    try:
        d = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:]))
    except ValueError:
        return None
    channel = re.sub(r"\s+", " ", m.group(3)).strip()
    if not channel:
        return None
    return VideoTitle(source_tag=m.group(1).lower(), video_date=d, channel=channel)
