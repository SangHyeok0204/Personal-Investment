"""이 맥의 `claude` CLI 를 **격리해서** 부른다 (계획 B2 — 사용자 결정 2).

원본 호출 지점 두 곳(`llm_cli.py` = codex exec 드롭인, `web_fallback.py` = `claude -p` + 웹 검색)을 여기 하나로 모은다.
`web_fallback` 의 "LLM 에게 웹에서 실적을 찾게 하기"는 버린다 — 도구를 주면 8-K 원문(외부 텍스트)이 프롬프트
주입 경로가 된다. 실적 숫자는 Nasdaq · SEC 수집기(B3a · B4)가 가져오고, LLM 은 **받은 글만** 읽는다.

격리(리뷰 반영):
  - **절대경로**(`CLAUDE_BIN`, 기본 `~/.npm-global/bin/claude`) — LaunchAgent 의 PATH 에는 npm 경로가 없다.
  - `--tools ""`(도구 전부 끔) · `--strict-mcp-config` + 빈 MCP · `--setting-sources ""`(사용자·프로젝트 설정/훅 안 읽음)
    · `--no-session-persistence` · 임시 폴더를 작업 폴더로.
  - ⚠️`--bare` 는 쓰지 않는다 — 키체인 읽기를 건너뛰어 이 맥의 로그인(OAuth) 세션이 안 잡힌다.
  - 타임아웃 원본대로 **500초**(`watching_points.py:115`) — 3분이면 대량 시간초과.
쿼터: 사용자의 대화형 사용과 **같은 한도를 나눠 쓴다** → 하루 호출 상한(`LLM_DAILY_CAP`, 기본 40) ·
  "사용량 초과"는 "로그아웃"과 구분해 표시하고 **재시도하지 않는다**.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TIMEOUT = 500
KST = ZoneInfo("Asia/Seoul")

# 오류 → 종류. 화면(/data-operations)은 이 종류를 그대로 보인다.
_LOGGED_OUT = re.compile(r"not logged in|please run /login|invalid api key|authenticat|oauth token|/login", re.I)
_USAGE = re.compile(r"usage limit|limit reached|rate.?limit|quota|credit balance|too many requests|overloaded", re.I)


class LlmError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind      # 'logged_out' | 'usage_limit' | 'timeout' | 'cap' | 'missing' | 'stopped' | 'other'


@dataclass
class LlmResult:
    text: str
    model: str | None
    cost_usd: float | None
    duration_ms: int
    calls_today: int


def claude_bin() -> str:
    for cand in (os.environ.get("CLAUDE_BIN"), str(Path.home() / ".npm-global" / "bin" / "claude"),
                 shutil.which("claude")):
        if cand and os.path.exists(cand):
            return cand
    raise LlmError("missing", "claude CLI 를 찾지 못함 — CLAUDE_BIN 을 절대경로로 지정")


def classify(text: str) -> str:
    if _LOGGED_OUT.search(text or ""):
        return "logged_out"
    if _USAGE.search(text or ""):
        return "usage_limit"
    return "other"


# ── 하루 호출 상한(맥 한 대 — 파일 카운터) ─────────────────────────────────────


def _counter_path(storage_dir: str | None) -> Path:
    base = Path(storage_dir or os.environ.get("STORAGE_DIR") or tempfile.gettempdir()) / "llm"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"calls-{datetime.now(KST):%Y-%m-%d}.json"


@contextmanager
def _counter_lock(path: Path):
    # ★(M2) 읽기-더하기-쓰기를 한 덩어리로 — 스레드·프로세스가 겹쳐도 셈이 빠지지 않게.
    #   데이터 파일은 os.replace 로 inode 가 바뀌므로 잠금은 옆의 .lock 파일에 건다.
    with open(path.with_suffix(".lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _count(data: dict) -> int:
    try:
        return int(data.get("n", 0))
    except (TypeError, ValueError):
        return 0


def _write(path: Path, data: dict) -> None:
    # 임시 파일 → os.replace: 쓰다 죽어도 반쪽 JSON 이 남지 않는다. (잠금 안에서만 부른다)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(data))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def calls_today(storage_dir: str | None = None) -> int:
    path = _counter_path(storage_dir)
    with _counter_lock(path):
        return _count(_read(path))


def _bump(storage_dir: str | None) -> int:
    path = _counter_path(storage_dir)
    with _counter_lock(path):
        data = _read(path)
        n = _count(data) + 1
        _write(path, {**data, "n": n})
    return n


def _add_cost(storage_dir: str | None, cost_usd) -> None:
    """★(B1-e) CLI 의 `total_cost_usd` 를 그날 카운터 파일의 `usd_notional` 에 더한다 — 기록만, 막지 않는다."""
    if not isinstance(cost_usd, (int, float)) or isinstance(cost_usd, bool):
        return
    path = _counter_path(storage_dir)
    with _counter_lock(path):
        data = _read(path)
        try:
            prev = float(data.get("usd_notional") or 0)
        except (TypeError, ValueError):
            prev = 0.0
        _write(path, {**data, "n": _count(data), "usd_notional": round(prev + float(cost_usd), 6)})


def daily_cap() -> int:
    return int(os.environ.get("LLM_DAILY_CAP", "40"))


def stop_reason(storage_dir: str | None = None) -> str | None:
    """★(B1) 비상 정지 — `storage/llm/STOP` 파일이 있거나 `LLM_DAILY_CAP=0` 이면 그 까닭, 아니면 None.

    run_claude 는 호출 전에, worker 는 llm 큐 작업을 집기 전에 본다(작업은 PENDING 으로 남는다).
    """
    if (_counter_path(storage_dir).parent / "STOP").exists():
        return "STOP 파일(storage/llm/STOP) 있음 — 지우면 다시 돈다"
    if daily_cap() <= 0:
        return "LLM_DAILY_CAP=0 — 설정으로 멈춤"
    return None


def run_claude(prompt: str, *, timeout: int = DEFAULT_TIMEOUT, model: str | None = None,
               storage_dir: str | None = None, runner=subprocess.run) -> LlmResult:
    """프롬프트 → 답 글. 실패는 종류가 붙은 `LlmError`(부르는 쪽이 원천 상태에 적는다)."""
    reason = stop_reason(storage_dir)
    if reason:                      # ★(B1) 상한 확인·_bump 보다 먼저 — 호출로 세지 않는다
        raise LlmError("stopped", reason)
    if calls_today(storage_dir) >= daily_cap():
        raise LlmError("cap", f"오늘 호출 상한 {daily_cap()}회에 닿음 — 대화형 사용과 한도를 나눠 쓴다")
    cmd = [claude_bin(), "-p", "-", "--output-format", "json", "--tools", "",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--setting-sources", "", "--no-session-persistence"]
    if model:
        cmd += ["--model", model]
    n = _bump(storage_dir)          # 시도 횟수로 센다(실패도 한도를 쓴다)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="llm-") as cwd:
        try:
            proc = runner(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                          encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            raise LlmError("timeout", f"CLI 응답 {timeout}초 초과") from exc
    out, err = proc.stdout or "", proc.stderr or ""
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if proc.returncode != 0 or not isinstance(data, dict) or data.get("is_error"):
        msg = (data or {}).get("result") if isinstance(data, dict) else None
        text = f"{msg or ''} {err} {out if data is None else ''}".strip()
        raise LlmError(classify(text), text[:300] or f"exit {proc.returncode}")
    models = list((data.get("modelUsage") or {}).keys())
    _add_cost(storage_dir, data.get("total_cost_usd"))
    return LlmResult(text=str(data.get("result") or ""), model=models[0] if models else model,
                     cost_usd=data.get("total_cost_usd"), duration_ms=int((time.monotonic() - t0) * 1000),
                     calls_today=n)
