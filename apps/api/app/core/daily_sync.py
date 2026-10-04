"""영업일 16:30(KST) 이력 동기화 — 체결·주문·배당·실현손익·일별성과.

★2026-09-23 사용자 요청: 국내 체결내역을 영업일마다 자동으로 받아 둘 것.
  (처음 요청은 06:00 이었으나, 그 시간대는 증권사 배치라 이력이 **에러 없이
  빈 배열**로 온다 — README '이른 아침에는 동기화하지 말 것' 참고. 국내장
  마감(15:30) 직후인 16:30 으로 옮겼다. 당일 체결을 같은 날 받는다.)

[왜 '타이머'가 아니라 '따라잡기'인가]
이건 노트북에서 도는 1인용 대시보드다. 16:30 에 맥이 자고 있거나 uvicorn 이
꺼져 있으면 정각 타이머는 그냥 그 날을 통째로 건너뛴다 — 그리고 아무도 모른다.
그래서 시각을 맞추는 대신 **"가장 최근에 지나간 영업일 16:30 이후로 한 번도
안 돌았으면 지금 돈다"** 로 판정한다. 켜는 순간 밀린 것을 따라잡는다.

판정 근거는 새 상태 파일이 아니라 `jobs` 테이블의 마지막 SYNC_KIWOOM_PORTFOLIO
시각이다 — 수동으로 돌렸으면 그것도 그대로 인정된다(중복 실행을 안 한다).
★2026-10-05 '마지막'은 **제대로 받아 온** 회차다(`last_good_sync_at` — 수집 신선도와 같은 정의).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, not_, select

from app.core import credentials_store
from app.db.session import SessionLocal
from app.models import Job

KST = ZoneInfo("Asia/Seoul")

#: 국내장 마감(15:30) 직후. 당일 체결이 원장에 올라온 뒤다.
RUN_HOUR, RUN_MINUTE = 16, 30

#: 밀린 게 있는지 확인하는 주기. 확인은 조회 한 번이라 가볍다.
CHECK_INTERVAL_SECONDS = 60.0

#: ⚠️증권사 일일 배치 시간대(KST). 이 안에서는 이력이 **에러 없이 빈 배열**로
#:  온다(실측 2026-09-22 07:00, usa21670 이 0행 / 같은 조회가 23시엔 530행).
#:  따라잡기가 하필 이 시간에 깨어날 수 있으므로 여기서도 막는다 — 안 막으면
#:  "따라잡았다"고 기록만 남기고 내용은 비운다.
BATCH_WINDOW_START_HOUR = 5
BATCH_WINDOW_END_HOUR = 7

#: ⚠️배치 시간대 밖에서도 일별성과가 **0건**으로 오는 때가 있다(실측 2026-10-03 토 09:12 —
#:  그 회차를 '따라잡음'으로 세는 바람에 10-02 미국장 마감분이 월요일 16:30 까지 비었다).
#:  usa21670 은 기간 전체를 주므로(평소 500행 넘게) 0건은 '받을 게 없음'이 아니라 빈 응답이다.
#:  그런 회차는 이 시간이 지나면 없던 것으로 보고 다시 돈다 — 1분마다 두드리지 않도록 간격을 둔다.
#: ★2026-10-05 키움이 FAILED 를 돌려준 회차도 같은 간격으로 다시 돈다(예전엔 다음 영업일 16:30
#:  까지 기다렸다 — 일시 장애 한 번에 하루 치가 빠졌다).
RETRY_AFTER = timedelta(hours=2)


def last_scheduled_run(now: datetime | None = None) -> datetime:
    """가장 최근에 지나간 '영업일 16:30 KST'.

    ⚠️공휴일은 보지 않는다 — 휴장일에 돌려도 받을 게 없어 0건일 뿐이고,
      한 번 더 받아 보는 쪽이 건너뛰는 것보다 안전하다(`_last_us_close` 와 같은
      판단이다).
    """
    kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    candidate = kst.replace(hour=RUN_HOUR, minute=RUN_MINUTE, second=0, microsecond=0)
    if candidate > kst:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:  # 토·일
        candidate -= timedelta(days=1)
    return candidate


def in_batch_window(now: datetime | None = None) -> bool:
    kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    return BATCH_WINDOW_START_HOUR <= kst.hour < BATCH_WINDOW_END_HOUR


#: ★2026-10-05 '시작했는데 끝나지 않은' 동기화를 살아 있다고 볼 시간. 실측 한 회차는 ~2분이다.
#:  이보다 오래된 RUNNING 은 죽은 것(재시작으로 끊김)으로 본다 — 새 동기화를 막지 않는다.
RUNNING_STALE_AFTER = timedelta(minutes=15)

#: ★2026-10-05 재시작으로 끊겨 닫힌 회차 표시(`jobs.result`). 진짜 실패와 구분한다 —
#:  이 회차는 재시도 간격을 걸지 않는다(켜자마자 따라잡는다).
ORPHANED_RESULT = {"orphaned": True}

_SYNC = Job.job_type == "SYNC_KIWOOM_PORTFOLIO"
_AT = func.coalesce(Job.finished_at, Job.created_at)
#: ★2026-10-05 '제대로 받아 온' 회차의 단일 정의 — 수집 신선도(stale)와 16:30 따라잡기가
#:  **같은 조건**을 쓴다. 성공 + 일별성과 0건이 아님(result 가 없던 옛 행은 받은 것으로 본다).
#:  ⚠️예전엔 두 곳이 따로 판정했다 — 화면은 '뒤처짐'인데 루프는 '따라잡음'으로 세는 식으로 어긋났다.
_GOOD = and_(
    Job.status == "SUCCESS",
    func.coalesce(Job.result["daily_performance"].as_integer(), 1) != 0,
)


def last_good_sync_at(db) -> datetime | None:
    """제대로 받아 온 마지막 이력 동기화 시각. 진행 중·실패·0건·끊긴 회차는 세지 않는다."""
    return db.execute(select(func.max(_AT)).where(_SYNC, _GOOD)).scalar()


def last_bad_attempt_at(db) -> datetime | None:
    """끝까지 돌았지만 못 받아 온 마지막 회차(키움 FAILED·일별성과 0건) 시각.

    ⚠️재시작으로 끊긴 회차(`ORPHANED_RESULT`)는 뺀다 — 그건 키움이 거절한 게 아니라
      우리가 끊은 것이라, 켜자마자 다시 도는 게 맞다.
    """
    orphaned = func.coalesce(Job.result["orphaned"].as_boolean(), False)
    return db.execute(
        select(func.max(_AT)).where(
            _SYNC, Job.status.in_(("SUCCESS", "FAILED")), not_(_GOOD), not_(orphaned)
        )
    ).scalar()


def sync_running(db, now: datetime | None = None) -> bool:
    """`RUNNING_STALE_AFTER` 안에 시작한 RUNNING 동기화가 있는가."""
    since = (now or datetime.now(timezone.utc)) - RUNNING_STALE_AFTER
    return db.execute(
        select(Job.id).where(
            _SYNC, Job.status == "RUNNING", func.coalesce(Job.started_at, Job.created_at) >= since
        ).limit(1)
    ).first() is not None


def is_due(
    last_good_at: datetime | None,
    now: datetime | None = None,
    last_bad_at: datetime | None = None,
) -> bool:
    """제대로 받은 마지막 회차가 '가장 최근 영업일 16:30' 보다 이전이면 밀린 것이다.

    ★2026-10-05 단, 그 16:30 이후 **못 받아 온 회차**(FAILED·0건)가 `RETRY_AFTER` 안에
      있으면 기다린다 — 키움이 거절하는 동안 1분마다 두드리지 않는다.
      16:30 이전의 실패는 이번 회차의 시도가 아니므로 기다리지 않는다.
    """
    now = now or datetime.now(timezone.utc)
    mark = last_scheduled_run(now)
    if last_good_at is not None and last_good_at >= mark:
        return False
    if last_bad_at is not None and last_bad_at >= mark and last_bad_at > now - RETRY_AFTER:
        return False
    return True


def _run_once() -> str | None:
    """밀렸으면 동기화한다. 실제로 돌았으면 요약 문자열, 아니면 None.

    ⚠️엔드포인트 함수를 그대로 부른다. 이 파일이 잡 생성·종료·핸들러 호출을
      다시 구현하면 수동 동기화와 자동 동기화가 **다른 코드**가 되고, 한쪽만
      고쳐지는 날이 온다(brokerage.py 머리말의 판단과 같다).
    """
    from app.api import brokerage
    from app.core.errors import AppError

    if not credentials_store.read_settings().get("configured"):
        return None
    if in_batch_window():
        return None

    with SessionLocal() as db:
        if not is_due(last_good_sync_at(db), last_bad_at=last_bad_attempt_at(db)):
            return None
        try:
            result = brokerage.run_sync(db=db)
        except AppError as exc:
            # ★2026-10-05 수동 동기화가 이미 돌고 있으면(409) 조용히 넘긴다 — 그 회차가
            #   끝나면 다음 확인에서 '따라잡음'으로 잡힌다.
            if exc.code == "SYNC_IN_PROGRESS":
                return None
            raise
    return f"체결 {result.trades}건 / 실현손익 {result.realized_pnl}건"


async def daily_sync_loop() -> None:
    """1분마다 '밀렸나'만 묻고, 밀렸을 때만 동기화한다."""
    while True:
        try:
            # ⚠️동기화는 실측 ~2분 걸리는 **블로킹** 호출이다. 이벤트 루프에서
            #   그대로 돌리면 그동안 API 가 통째로 멎는다 — 화면이 죽는다.
            await asyncio.to_thread(_run_once)
        except Exception:  # noqa: BLE001 — 루프는 절대 죽지 않는다
            # 실패해도 jobs 에 FAILED 로 남는다. 다음 확인에서 다시 밀린 것으로
            # 잡히지만, ★2026-10-05 `RETRY_AFTER`(2시간) 안에는 재시도하지 않는다
            # — 1분마다 키움을 두드리지 않는다(`is_due`).
            pass
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
