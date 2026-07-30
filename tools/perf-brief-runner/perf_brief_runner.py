"""[성과보고] Windows 러너 — claude 서브프로세스로 완성 보고서를 만든다 (2026-07-28).

대시보드 [보고서 생성] 버튼 → api → collector → (host.docker.internal:8010) → 여기.

왜 Windows 인가: claude CLI 가 이 PC 에만 있고 인증이 구독 OAuth(.credentials.json)라
컨테이너로 옮길 수 없다(옮기려면 별도 API 키 발급이 필요). 그래서 계산은 컨테이너가,
서사 작성은 이 러너가 맡는 2단 구조.

  1. collector 의 /perf-brief/analyze 를 호출해 **확정 수치**를 받는다(검증된 엔진 재사용).
  2. 스키마 + 완성 보고서 2종 예시 + 그 수치로 프롬프트를 만든다.
  3. claude -p 로 뉴스 조사 + 서사를 채워 완성 JSON 을 받는다. 수치는 못 바꾸게 못박는다.
  4. 검증 후 정기미팅 폴더에 daily_*.json / weekly_*.json 으로 저장 → 기존 배선이 렌더.

표준 라이브러리만 쓴다(사내 PC 파이썬 환경 가정 최소화). 한 번에 한 작업만 돈다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BRIEF_DIR = Path(os.environ.get("PERF_BRIEF_DIR", r"S:\GE\Wonjae\07_회의자료\정기미팅"))
SCHEMA_MD = BRIEF_DIR / "perf-brief-skill" / "references" / "json_schema.md"
EXAMPLE_DAILY = BRIEF_DIR / "daily_20260723.json"
EXAMPLE_WEEKLY = BRIEF_DIR / "weekly_20260717_20260724.json"
BACKUP_DIR = BRIEF_DIR / "backup"

ANALYZE_URL = os.environ.get("PERF_BRIEF_ANALYZE_URL", "http://localhost:8000/api/v1/inav/perf-brief/analyze")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude.exe"))
CLAUDE_MODEL = os.environ.get("PERF_BRIEF_MODEL", "opus")
CLAUDE_TIMEOUT_S = int(os.environ.get("PERF_BRIEF_TIMEOUT_S", "900"))
PORT = int(os.environ.get("PERF_BRIEF_RUNNER_PORT", "8010"))
# 설정하면 X-Runner-Token 헤더가 일치할 때만 실행을 받는다. 비우면 검사하지 않는다.
TOKEN = os.environ.get("PERF_BRIEF_RUNNER_TOKEN", "").strip()

WORK_DIR = Path(os.environ.get("PERF_BRIEF_WORK_DIR", str(Path.home() / ".perf-brief-runner")))

_lock = threading.Lock()
_job: dict = {"status": "idle", "mode": None, "startedAt": None, "finishedAt": None,
              "log": [], "error": None, "savedAs": None}


def _log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    _job["log"].append(line)
    del _job["log"][:-40]  # 최근 40줄만 보관


# ── 프롬프트 ────────────────────────────────────────────────────────────

PROMPT = """당신은 한국투자신탁운용 매니저의 아침 발표용 성과 브리프를 작성합니다.
결과물은 **완성된 보고서 JSON 하나**이며, 사내 대시보드가 이 JSON 을 그대로 렌더합니다.

━━ 절대 규칙 ━━
1. 아래 [확정 수치]는 검증된 계산 엔진이 운용역 소스 엑셀에서 산출한 값입니다.
   **모든 수치·라벨·부호를 그대로 옮기십시오. 재계산·반올림 변경·추정 금지.**
   당신이 만들 것은 오직 ① 뉴스 조사에 근거한 원인 규명과 ② 서사입니다.
2. 출력은 **JSON 본문만**. 코드블록(```), 머리말, 맺음말, 설명 문장을 붙이지 마십시오.
3. 이 작업은 **직접 수행**하십시오. 다른 에이전트에 위임하지 마십시오.
4. 원인을 못 찾은 등락은 추측하지 말고 "단독 악재 미확인·수급성" 식으로 정직하게 쓰십시오.

━━ 당신이 채워야 하는 것 (빠짐없이) ━━
- `market`: 시장 스트립 4칩. 그 기간 시장을 규정한 사건. 수치가 있으면 value+tone.
- 각 섹션의 `blocks` 안에 **`stories` 블록**(랩 2개 · 펀드 3개)을 적절한 위치에 끼워 넣기.
  리듬 고정: `verdict`(판정 한 줄) + `tag`(±bp 등) → `body`(메커니즘 2~3문장, 숫자·인과·
  뉴스 근거) → `watch`(다음에 볼 것 한 줄). 종목 나열 금지.
- 모든 차트 블록의 `caption`: 그 차트의 한 줄 인사이트(무엇이 그림을 지배했는지).
- `checkpoints`: 관전 포인트 3개. 데일리는 "TODAY — 관전 포인트", 위클리는
  "NEXT WEEK — 관전 포인트".
- `footnote`: [확정 수치]의 footnote 를 **기반으로** 하되, [QA 경고]의 내용과 근사치·
  결측·자체분류를 빠짐없이 반영해 다시 쓰십시오.
- `eyebrow`/`title`: 분석본이 아니라 보고서 문구로 바꾸십시오
  (예: "DAILY PERFORMANCE BRIEF" / "운용자산 데일리 성과 보고").

[확정 수치]에 이미 들어 있는 것(그대로 보존): kind, asOf, period, dateLine, dateNote,
sections 의 scores·bars·dualBars·path 블록과 그 rows/days 값 전부.

━━ 조사 지침 ━━
WebSearch 로 (a) 해당 기간 시장 요약, (b) 기여도·초과수익 상·하위 종목의 등락 원인,
(c) 마감 후 실적 발표 여부를 확인하십시오. 데일리 4~7회, 위클리 5~10회 규모.
마감 후 발표는 당일 수익률에 미반영이므로 스토리·관전 포인트에서 다루십시오.

━━ 인라인 마크업 (HTML 태그 금지) ━━
`**굵게**` · `{{+양수 강조}}` · `{{-음수 강조}}`

━━━━━━━━━━ 출력 스키마 ━━━━━━━━━━
{schema}

━━━━━━━━━━ 완성 보고서 예시 1 (데일리) ━━━━━━━━━━
{example_daily}

━━━━━━━━━━ 완성 보고서 예시 2 (위클리) ━━━━━━━━━━
{example_weekly}

━━━━━━━━━━ [QA 경고] ━━━━━━━━━━
{warnings}

━━━━━━━━━━ [확정 수치] ━━━━━━━━━━
{analysis}

━━━━━━━━━━
위 [확정 수치]를 토대로 {kind_ko} 성과보고 JSON 을 완성해 출력하십시오. JSON 본문만.
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _build_prompt(analysis: dict) -> str:
    kind = analysis["kind"]
    lean = {k: v for k, v in analysis.items() if k != "warnings"}
    return PROMPT.format(
        schema=_read(SCHEMA_MD),
        example_daily=_read(EXAMPLE_DAILY),
        example_weekly=_read(EXAMPLE_WEEKLY),
        warnings="\n".join(f"- {w}" for w in analysis.get("warnings") or []) or "(없음)",
        analysis=json.dumps(lean, ensure_ascii=False, indent=1),
        kind_ko="데일리" if kind == "daily" else "위클리",
    )


# ── claude 호출 ─────────────────────────────────────────────────────────

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _extract_json(text: str) -> dict:
    """모델 출력에서 JSON 본문을 뽑는다. 코드펜스·앞뒤 잡문을 견딘다."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("출력에서 JSON 을 찾지 못했습니다")
    return json.loads(cleaned[start:end + 1])


def _run_claude(prompt: str) -> dict:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["DISABLE_OMC"] = "1"  # 사용자 전역 CLAUDE.md 의 오케스트레이션 레이어를 끈다
    cmd = [
        CLAUDE_BIN, "-p",
        "--output-format", "json",
        "--model", CLAUDE_MODEL,
        "--allowedTools", "WebSearch,WebFetch",
        "--permission-mode", "acceptEdits",
        "--strict-mcp-config",
    ]
    _log(f"claude 실행 (model={CLAUDE_MODEL}, 프롬프트 {len(prompt):,}자)")
    t0 = time.time()
    proc = subprocess.run(
        cmd, input=prompt, cwd=str(WORK_DIR), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=CLAUDE_TIMEOUT_S,
    )
    _log(f"claude 종료 rc={proc.returncode} ({time.time() - t0:.0f}초)")
    if proc.returncode != 0:
        raise RuntimeError(f"claude 실패 rc={proc.returncode}: {(proc.stderr or '')[-500:]}")

    envelope = _extract_json(proc.stdout)
    # --output-format json 은 {type, subtype, is_error, result, ...} 봉투로 감싼다.
    body = envelope.get("result") if isinstance(envelope, dict) and "result" in envelope else None
    if envelope.get("is_error"):
        raise RuntimeError(f"claude 오류 응답: {str(body)[:300]}")
    if body is None:
        return envelope  # 봉투 없이 곧바로 보고서를 준 경우
    return _extract_json(body) if isinstance(body, str) else body


# ── 검증·저장 ───────────────────────────────────────────────────────────

def _validate(report: dict, analysis: dict) -> None:
    """수치가 보존됐는지, 서사가 채워졌는지 확인. 어긋나면 저장하지 않는다."""
    if report.get("kind") != analysis["kind"]:
        raise ValueError(f"kind 불일치: {report.get('kind')} != {analysis['kind']}")
    if report.get("asOf") != analysis["asOf"]:
        raise ValueError(f"asOf 불일치: {report.get('asOf')} != {analysis['asOf']}")

    src = {s["id"]: s for s in analysis["sections"]}
    got = {s.get("id"): s for s in report.get("sections") or []}
    missing = set(src) - set(got)
    if missing:
        raise ValueError(f"섹션 누락: {sorted(missing)}")

    for sid, ssrc in src.items():
        sgot = got[sid]
        if [x["value"] for x in ssrc["scores"]] != [x.get("value") for x in sgot.get("scores") or []]:
            raise ValueError(f"[{sid}] 스코어카드 값이 변경됨 — 수치 보존 위반")
        # 차트 블록의 행 값이 그대로인지 (stories 는 새로 추가되므로 제외)
        chart_src = [b for b in ssrc["blocks"] if b["type"] in ("bars", "dualBars", "path")]
        chart_got = [b for b in (sgot.get("blocks") or []) if b.get("type") in ("bars", "dualBars", "path")]
        if len(chart_src) != len(chart_got):
            raise ValueError(f"[{sid}] 차트 블록 개수 불일치 {len(chart_src)} → {len(chart_got)}")
        for a, b in zip(chart_src, chart_got):
            ka = "days" if a["type"] == "path" else "rows"
            va = [tuple(sorted((k, v) for k, v in x.items() if isinstance(v, (int, float)))) for x in a[ka]]
            vb = [tuple(sorted((k, v) for k, v in x.items() if isinstance(v, (int, float)))) for x in (b.get(ka) or [])]
            if va != vb:
                raise ValueError(f"[{sid}] '{a['title']}' 수치가 변경됨 — 수치 보존 위반")

    if not report.get("market"):
        raise ValueError("market(시장 스트립)이 비었습니다")
    stories = sum(len(b.get("items") or [])
                  for s in report["sections"] for b in (s.get("blocks") or [])
                  if b.get("type") == "stories")
    if stories < 2:
        raise ValueError(f"스토리 카드가 {stories}개뿐입니다")
    if not (report.get("checkpoints") or {}).get("items"):
        raise ValueError("checkpoints(관전 포인트)가 비었습니다")


def _target_path(report: dict) -> Path:
    if report["kind"] == "weekly":
        p = report.get("period") or {}
        s, e = (p.get("start") or "").replace("-", ""), (p.get("end") or "").replace("-", "")
        return BRIEF_DIR / f"weekly_{s}_{e}.json"
    return BRIEF_DIR / f"daily_{report['asOf'].replace('-', '')}.json"


def _save(report: dict) -> Path:
    target = _target_path(report)
    if target.exists():  # 손으로 만든 보고서를 덮어쓰지 않도록 백업부터
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(target, BACKUP_DIR / f"{target.stem}_{stamp}{target.suffix}")
        _log(f"기존 파일 백업 → backup/{target.stem}_{stamp}{target.suffix}")
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)  # 부분 저장 상태가 대시보드에 읽히지 않게 원자적 교체
    return target


# ── 작업 ────────────────────────────────────────────────────────────────

def _generate(mode: str) -> None:
    try:
        _log(f"[1/4] 확정 수치 조회 ({mode})")
        with urllib.request.urlopen(f"{ANALYZE_URL}?mode={mode}", timeout=120) as r:
            analysis = json.load(r)
        if "sections" not in analysis:
            raise RuntimeError(f"분석 응답 이상: {str(analysis)[:200]}")
        _log(f"      기준 {analysis['asOf']} · 소스 {analysis['source']} "
             f"(저장 {analysis['sourceSavedAt']}) · QA경고 {len(analysis.get('warnings') or [])}건")

        _log("[2/4] 프롬프트 구성")
        prompt = _build_prompt(analysis)

        _log("[3/4] claude 로 뉴스 조사 + 서사 작성 (수 분 소요)")
        report = _run_claude(prompt)
        report["writtenOn"] = date.today().isoformat()  # 대시보드의 '오늘 보고서' 판정 키
        report["schema"] = 1

        _log("[4/4] 검증 후 저장")
        _validate(report, analysis)
        target = _save(report)
        _log(f"완료 → {target.name}")
        with _lock:
            _job.update(status="done", finishedAt=datetime.now().isoformat(timespec="seconds"),
                        savedAs=target.name, error=None)
    except Exception as exc:  # noqa: BLE001
        _log(f"실패: {type(exc).__name__}: {exc}")
        with _lock:
            _job.update(status="failed", finishedAt=datetime.now().isoformat(timespec="seconds"),
                        error=f"{type(exc).__name__}: {exc}")


# ── HTTP ────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 접근 로그 억제 (작업 로그만 남긴다)
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        return not TOKEN or self.headers.get("X-Runner-Token") == TOKEN

    def _status(self) -> dict:
        with _lock:
            j = dict(_job)
        if j["status"] == "running" and j["startedAt"]:
            started = datetime.fromisoformat(j["startedAt"])
            j["elapsedSec"] = int((datetime.now() - started).total_seconds())
        return j

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"status": "ok", "claude": Path(CLAUDE_BIN).exists()})
        if path == "/status":
            return self._send(200, self._status())
        self._send(404, {"detail": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/generate":
            return self._send(404, {"detail": "not found"})
        if not self._authed():
            return self._send(403, {"detail": "bad token"})
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        mode = (parse_qs(parsed.query).get("mode") or ["daily"])[0]
        if mode not in ("daily", "weekly"):
            return self._send(400, {"detail": f"unknown mode: {mode}"})
        with _lock:
            if _job["status"] == "running":
                return self._send(409, {"detail": "already running", **_job})
            _job.update(status="running", mode=mode, startedAt=datetime.now().isoformat(timespec="seconds"),
                        finishedAt=None, log=[], error=None, savedAs=None)
        threading.Thread(target=_generate, args=(mode,), daemon=True).start()
        return self._send(202, self._status())


def main() -> int:
    for p in (SCHEMA_MD, EXAMPLE_DAILY, EXAMPLE_WEEKLY):
        if not p.exists():
            print(f"[경고] 프롬프트 재료 없음: {p}", file=sys.stderr)
    if not Path(CLAUDE_BIN).exists():
        print(f"[경고] claude 실행파일 없음: {CLAUDE_BIN}", file=sys.stderr)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[성과보고 러너] http://0.0.0.0:{PORT}  (claude={CLAUDE_BIN}, model={CLAUDE_MODEL})", flush=True)
    print(f"  보고서 폴더: {BRIEF_DIR}", flush=True)
    print(f"  토큰 검사: {'ON' if TOKEN else 'OFF'}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("종료", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
