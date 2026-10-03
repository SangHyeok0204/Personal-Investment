"""작업 안 1회 수리 재시도 + 에스컬레이션 패킷 (하네스 L1).

예전: 응답이 형식 · 검증에서 떨어지면 작업이 FAILED 로 끝나고, `sec_sync.llm_catchup` 이 1시간 뒤 **같은 프롬프트**를
  다시 보냈다(검증 오류는 모델에 한 번도 전달되지 않았다).
지금: 같은 작업 안에서 한 번만 더 부른다 — 원래 프롬프트 + `fence("검증 오류", …)` + 고침 지시. 작업당 최대 2회.
  - `LlmError`(상한 cap · 로그아웃 · 사용량 초과 · 시간초과 · STOP 등)는 **수리하지 않고** 그대로 올린다 — 고칠 응답이 없다.
  - 수리 호출도 `run_claude` 를 거치므로 하루 상한(`LLM_DAILY_CAP`)에 그대로 센다.
  - 수리도 실패하면 `RepairFailed` — 부르는 쪽이 `write_escalation` 으로 패킷을 남기고, 따라잡기는 그 발표를 건너뛴다.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from llm.cli import KST, LlmResult
from llm.fence import fence

REPAIR_INSTRUCTION = "같은 자료로 위 오류만 고쳐 JSON 하나로 다시"
SAFE_DEFAULT = "leave null, show 미확인"


class RepairFailed(ValueError):
    """수리 호출까지 검증에서 떨어졌다. 메시지 = 마지막 검증 오류."""

    def __init__(self, warns: list[str], prompt: str, calls: int, last_text: str):
        super().__init__("; ".join(warns) or "검증 실패")
        self.warns, self.prompt, self.calls, self.last_text = list(warns), prompt, calls, last_text


@dataclass
class Repaired:
    data: object
    warns: list[str]
    result: LlmResult
    calls: int


def repair_prompt(prompt: str, warns: list[str]) -> str:
    return f"{prompt}\n\n{fence('검증 오류', chr(10).join(warns))}\n{REPAIR_INSTRUCTION}"


def run_with_repair(prompt: str, call, parse, validate, *, max_repairs: int = 1) -> Repaired:
    """`call(prompt) -> LlmResult`, `parse(text) -> data`, `validate(data) -> (ok, warns)`.

    통과하면 `Repaired`, 수리까지 실패하면 `RepairFailed`. `LlmError` 는 잡지 않는다(수리 없음).
    """
    current, warns, text = prompt, [], ""
    for n in range(1, max_repairs + 2):
        res = call(current)
        data = parse(res.text)
        ok, warns = validate(data)
        if ok:
            return Repaired(data, warns, res, n)
        text = res.text
        current = repair_prompt(prompt, warns)
    raise RepairFailed(warns, prompt, max_repairs + 1, text)


def write_escalation(storage_dir: str, job_type: str, event_id, failure: RepairFailed, *, task: str,
                     decision_needed: str, source: dict, job_id=None) -> Path:
    """`storage/llm/escalations/{date}-{job_type}-{event_id}.json` — 사람이 결정할 것을 한 장에."""
    base = Path(storage_dir) / "llm" / "escalations"
    base.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(event_id))
    path = base / f"{datetime.now(KST):%Y-%m-%d}-{job_type}-{safe_id}.json"
    packet = {
        "task": task,
        "decision_needed": decision_needed,
        "last_validator_errors": failure.warns,
        "prompt_sha256": hashlib.sha256(failure.prompt.encode("utf-8")).hexdigest(),
        "source": source,
        "alternatives_tried": ["원래 프롬프트 1회", "검증 오류를 펜스로 넣은 수리 1회"][:failure.calls],
        "safe_default": SAFE_DEFAULT,
        "job_type": job_type,
        "event_id": event_id,
        "job_id": str(job_id) if job_id else None,
        "created_at": datetime.now(KST).isoformat(),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(packet, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path
