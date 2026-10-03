"""작업별 벽시계 상한 (하네스 L4) — 2026-10-02 EARNINGS_REVENUE 가 18시간 RUNNING 으로 멈춘 사고의 대책.

그때 심장박동 스레드는 계속 뛰어서 리퍼가 손을 못 댔고, sec_crawl 큐 전체가 막혔다.
  - `process_job` 은 핸들러를 스레드에서 돌리고 `limit_for(job_type) + GRACE` 만 기다린다. 넘으면 FAILED
    `timeout_wallclock`. 심장박동도 상한을 넘기면 멈춘다(워커 자체가 굳어도 리퍼가 되살린다).
  - 스레드는 죽일 수 없다 — Playwright 처럼 파이프에 막히는 코드는 `run_in_child` 로 **자식 프로세스**에서 돌린다.
    시간이 다 되면 SIGTERM → (5초) → SIGKILL 을 자식의 프로세스 그룹과 미리 적어 둔 자손 전부에 보낸다.
    ⚠️Playwright 는 브라우저를 별도 세션(detached)으로 띄운다 — 그룹 kill 만으로는 크롬이 남는다. 그래서 자손 목록을 쓴다.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import signal
import subprocess
import threading
import time

# ★2026-10-03 실측(최근 30일 SUCCESS 의 소요시간 최댓값) × 약 1.5 로 잡는다. 처음엔 계획의 20/30분을 그대로
#   썼는데 EARNINGS_REVENUE 가 43·110·127분 걸린 성공 기록이 있었다 — 그대로 두면 정상 크롤이 매일 잘린다.
#   기록이 없는 작업 종류도 있어 기본값은 60분. 바꿀 때 API `ops_alerts.STUCK_LIMITS` 도 같이(테스트가 비교한다).
DEFAULT_LIMIT_SECONDS = 60 * 60
LIMITS = {
    "CUSIP_RESOLVE": 10 * 3600,        # 최대 377분
    "EARNINGS_REVENUE": 3 * 3600,      # 최대 127분 (2026-10-02 의 18시간 멈춤은 여기서 잘린다)
    "SEC_FORM4": 3 * 3600,             # 최대 112분
    "SEC_13DG": 2 * 3600,              # 최대 64분
    "SEC_13F_BACKFILL": 4 * 3600,      # 표본 1건 — 백필은 길 수 있어 넉넉히
    "SEASONALITY_APPEND": 3600,        # 최대 37분
    "SYNC_KIWOOM_PORTFOLIO": 3600,     # 최대 28분
}
# 자식 프로세스 쪽 시간초과가 먼저 터지도록(핸들러가 스스로 정리·원천 상태를 적는다) 스레드 쪽은 조금 더 기다린다.
GRACE_SECONDS = 15
KILL_GRACE_SECONDS = 5

_local = threading.local()


class WallClockTimeout(Exception):
    """작업의 벽시계 상한을 넘었다(error kind `timeout_wallclock`)."""


def limit_for(job_type: str) -> float:
    return LIMITS.get(job_type, DEFAULT_LIMIT_SECONDS)


def set_deadline(deadline: float | None) -> None:
    """이 스레드에서 도는 작업의 마감(`time.monotonic()` 기준). `run_in_child` 의 기본 시간이 된다."""
    _local.deadline = deadline


def remaining(default: float = DEFAULT_LIMIT_SECONDS) -> float:
    deadline = getattr(_local, "deadline", None)
    return default if deadline is None else max(1.0, deadline - time.monotonic())


def _child(q, fn, args, kwargs):
    os.setsid()          # 자식이 새 프로세스 그룹의 우두머리 — 손자(드라이버 등)가 그룹을 물려받는다
    try:
        q.put(("ok", fn(*args, **kwargs)))
    except BaseException as exc:     # noqa: BLE001 — 부모에게 그대로 넘긴다
        q.put(("err", exc))


def _descendants(pid: int) -> list[int]:
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    kids: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, stack = [], [pid]
    while stack:
        for c in kids.get(stack.pop(), []):
            found.append(c)
            stack.append(c)
    return found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_tree(proc) -> None:
    """자식 + 그 그룹 + 자손 전부: SIGTERM → 최대 5초 → SIGKILL. 자손은 먼저 적어 둔다(죽으면 고아로 흩어진다)."""
    pids = [proc.pid, *_descendants(proc.pid)]
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        if sig == signal.SIGTERM:
            end = time.monotonic() + KILL_GRACE_SECONDS
            while time.monotonic() < end and (proc.is_alive() or any(_alive(p) for p in pids[1:])):
                time.sleep(0.1)
    proc.join(KILL_GRACE_SECONDS)


def run_in_child(fn, *args, timeout: float | None = None, **kwargs):
    """`fn(*args, **kwargs)` 를 자식 프로세스에서. 시간이 넘으면 자손까지 죽이고 `WallClockTimeout`.

    `timeout` 이 없으면 지금 작업의 남은 벽시계 시간. `fn` 과 결과·예외는 pickle 가능해야 한다(spawn).
    """
    timeout = remaining() if timeout is None else timeout
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=_child, args=(q, fn, args, kwargs), daemon=True)
    proc.start()
    end = time.monotonic() + timeout
    try:
        while True:
            try:
                status, value = q.get(timeout=min(1.0, max(0.05, end - time.monotonic())))
                break
            except queue.Empty:
                if not proc.is_alive():
                    try:
                        status, value = q.get(timeout=1)
                        break
                    except queue.Empty:
                        raise RuntimeError(f"자식 프로세스가 결과 없이 끝남(exit {proc.exitcode})") from None
                if time.monotonic() >= end:
                    kill_tree(proc)
                    raise WallClockTimeout(
                        f"timeout_wallclock: {getattr(fn, '__name__', fn)} {int(timeout)}초 초과 — 자식 프로세스 강제 종료")
    finally:
        q.close()
    proc.join(KILL_GRACE_SECONDS)
    if proc.is_alive():
        kill_tree(proc)
    if status == "err":
        raise value
    return value
