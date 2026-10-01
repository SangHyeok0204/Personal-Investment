"""Plaud 녹음 읽기 — 공식 Plaud MCP 서버(`@plaud-ai/mcp`)를 자식 프로세스로 띄워 stdio 로 부른다.

★왜 이 길인가(2026-10-01 결정):
  - StudyAgent(`~/Developer/StudyAgent/engine/plaud.mjs`)가 이미 같은 방식으로 **무인 주기 실행**한다.
    `claude` CLI 를 거치지 않는다 — MCP 서버를 직접 띄워 JSON-RPC 두 가지(initialize · tools/call)만 쓴다.
  - 토큰은 MCP 서버가 `~/.plaud/tokens-mcp.json` 에서 읽고 **스스로 갱신**한다. 우리는 토큰을 만지지 않는다
    (읽지도 · 로그에 남기지도 않는다). 환경변수 키도 필요 없다.
  - Plaud HTTP API 를 직접 부르는 길은 공개 명세가 없다 — 서버 내부 구현을 흉내 내면 조용히 깨진다.
⚠️무인 실행이므로 `login` 도구는 **부르지 않는다**(브라우저가 열린다). 로그아웃이면 종류 'logged_out' 으로 실패하고
  터미널에서 `npx -y @plaud-ai/mcp@latest install` 을 한 번 돌려 달라고 화면에 적는다.
⚠️Plaud 의 시각은 `2026-09-29T12:11:03` 처럼 **시간대 없이** 오는데 UTC 다. 그냥 읽으면 한국에서 9시간 어긋난다.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone

PACKAGE = os.environ.get("PLAUD_MCP_PACKAGE") or "@plaud-ai/mcp@latest"
# 첫 실행은 npx 가 패키지를 받느라 오래 걸린다(StudyAgent 실측 기준 90초).
START_TIMEOUT = 90
CALL_TIMEOUT = 120

_AUTH = re.compile(r"401|not authenticated|unauthori[sz]ed|login", re.I)


class PlaudError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind      # 'logged_out' | 'timeout' | 'missing' | 'other'


def npx_bin() -> str:
    # LaunchAgent 의 PATH 는 plist 가 정한다(llm worker 는 /usr/local/bin 포함). 그래도 없으면 흔한 자리를 본다.
    for cand in (os.environ.get("NPX_BIN"), shutil.which("npx"), "/usr/local/bin/npx", "/opt/homebrew/bin/npx"):
        if cand and os.path.exists(cand):
            return cand
    raise PlaudError("missing", "npx 를 찾지 못함 — NPX_BIN 을 절대경로로 지정")


def unwrap(text: str) -> str:
    """Plaud 는 녹음 데이터를 `<untrusted-user-data-XXXX>` 로 감싸 준다(지시로 착각하지 말라는 표시). 데이터로만 쓰므로 벗긴다.

    머리글 문장 안에도 같은 태그 이름이 한 번 나온다 — 여는 태그는 **줄 맨 앞에 홀로 선 것**만 잡는다(StudyAgent 와 같다).
    """
    m = re.search(r"^<(untrusted-user-data-[0-9a-f]+)[^>\n]*>\n([\s\S]*?)\n</\1>", text or "", re.M)
    return m.group(2) if m else (text or "")


def parse_wrapped(text: str):
    try:
        return json.loads(unwrap(text))
    except ValueError:
        return None


def to_utc(v) -> datetime | None:
    """Plaud 시각 → UTC aware. 초·밀리초 숫자와 시간대 없는 문자열(=UTC)이 섞여 온다. 모르면 None."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or re.fullmatch(r"\d+", str(v).strip()):
        n = float(v)
        return datetime.fromtimestamp(n / 1000 if n >= 1e12 else n, tz=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def normalize_file(f: dict) -> dict:
    return {
        "id": str(f.get("id") or f.get("file_id") or ""),
        "name": str(f.get("name") or f.get("filename") or ""),
        "recorded_at": to_utc(f.get("start_at") or f.get("start_time") or f.get("created_at") or f.get("create_time")),
    }


class PlaudMcp:
    """아주 작은 MCP stdio 클라이언트. `with PlaudMcp() as p:` — 어느 길로 끝나든 자식을 닫는다
    (안 닫으면 npx 프로세스가 남아 쌓인다)."""

    def __init__(self, command: list[str] | None = None):
        self.command = command
        self.proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._next = 1

    def __enter__(self):
        cmd = self.command or [npx_bin(), "-y", PACKAGE]
        # 서버 로그는 stderr 로 나간다 — 버린다(토큰 갱신 기록 등이 섞일 수 있다). stdout 은 JSON-RPC 전용.
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", bufsize=1)
        threading.Thread(target=self._pump, daemon=True).start()
        try:
            self._request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "personal-investment", "version": "1"}}, START_TIMEOUT)
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
        self.proc = None

    def _pump(self):
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)       # 서버가 끝났다

    def _send(self, obj: dict):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _request(self, method: str, params: dict, timeout: float) -> dict:
        rid = self._next
        self._next += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty:
                raise PlaudError("timeout", f"Plaud MCP {method} 가 {timeout}초 안에 답하지 않음") from None
            if line is None:
                raise PlaudError("other", f"Plaud MCP 서버가 끝남 (code {self.proc.poll()})")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "method" in msg:          # 서버가 보내는 요청(ping 등) — 응답이 아니다
                if msg.get("method") == "ping" and msg.get("id") is not None:
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                continue
            if msg.get("id") != rid:
                continue
            if msg.get("error"):
                err = str(msg["error"].get("message") or msg["error"])
                raise PlaudError("logged_out" if _AUTH.search(err) else "other", err[:300])
            return msg.get("result") or {}

    def call(self, name: str, args: dict | None = None, timeout: float = CALL_TIMEOUT) -> str:
        """도구를 부르고 text 를 이어 붙여 돌려준다. 도구가 isError 를 세우면 던진다."""
        r = self._request("tools/call", {"name": name, "arguments": args or {}}, timeout)
        text = "\n".join(c.get("text", "") for c in r.get("content") or [] if c.get("type") == "text")
        if r.get("isError"):
            raise PlaudError("logged_out" if _AUTH.search(text) else "other", (text or f"{name} 실패")[:300])
        return text

    # ── 읽기 ────────────────────────────────────────────────────────────

    def check_login(self) -> None:
        """로그인돼 있는지만 본다. 사용자 정보는 쓰지 않는다."""
        self.call("get_current_user")

    def list_recent(self, date_from: str) -> tuple[list[dict], bool]:
        """`date_from`(YYYY-MM-DD) 이후 녹음. 반환: (목록, 다 훑었나).

        ⚠️서버는 최근 500건 안에서만 거른다(`complete=false` 면 그보다 오래된 구간은 안 봤다). 우리는 14일만 본다.
        """
        res = parse_wrapped(self.call("list_files", {"date_from": date_from}))
        if not isinstance(res, dict) and not isinstance(res, list):
            raise PlaudError("other", "list_files 응답을 읽지 못함")
        data = res if isinstance(res, list) else (res.get("data") or res.get("data_file_list") or [])
        complete = True if isinstance(res, list) else res.get("complete") is not False
        return [r for r in (normalize_file(f) for f in data if isinstance(f, dict)) if r["id"]], complete

    def transcript_text(self, file_id: str) -> str | None:
        """전사문 전체(말만 이어 붙임). 아직 전사 전이거나 없으면 None.

        정리본(`transaction_polish`)을 먼저, 없으면 원문(`transaction`). 없는 블록은 JSON 이 아닌 안내문으로 온다.
        """
        for block in ("transaction_polish", "transaction"):
            parts: list[str] = []
            cursor = None
            ok = True
            for _ in range(200):
                args = {"file_id": file_id, "block": block, "limit": 500}
                if cursor:
                    args["cursor"] = cursor
                try:
                    page = parse_wrapped(self.call("get_transcript", args))
                except PlaudError as exc:
                    if exc.kind == "logged_out":
                        raise
                    page = None
                if not isinstance(page, dict) or not isinstance(page.get("segments"), list):
                    ok = False
                    break
                for s in page["segments"]:
                    t = str(s.get("content") or s.get("text") or s.get("sentence") or "").strip() if isinstance(s, dict) else ""
                    if t:
                        parts.append(re.sub(r"\s+", " ", t))
                cursor = page.get("next_cursor")
                if not cursor:
                    break
            if ok and parts:
                return " ".join(parts)
        return None

    def ai_summary(self, file_id: str) -> str | None:
        """Plaud 가 만든 노트(AI 요약 탭 등)의 본문. 없으면 None."""
        try:
            notes = parse_wrapped(self.call("get_note", {"file_id": file_id}))
        except PlaudError as exc:
            if exc.kind == "logged_out":
                raise
            return None
        if not isinstance(notes, list):
            return None
        bodies = [str(n.get("data_content") or "").strip() for n in notes if isinstance(n, dict)]
        joined = "\n\n".join(b for b in bodies if b)
        return joined or None
