"""M2 — run-worker.sh 의 허용목록 env 로더: 허용 키만 · 감싼 따옴표 제거 · 기존 환경 우선 · 값 출력 없음."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "workers" / "run-worker.sh"


def _load(env_file, extra_env=None):
    probe = (
        'set -euo pipefail; RUN_WORKER_SOURCE_ONLY=1 source "$0"; '
        'load_env_local "$1" > "$2.out" 2>&1; '
        'for k in LLM_DAILY_CAP SEC_USER_AGENT DATABASE_URL PLAUD_TOKEN WORKER_POLL_INTERVAL_SECONDS '
        'OPENAI_API_KEY LLM_SINGLE; do printf "%s=[%s]\\n" "$k" "${!k-UNSET}"; done'
    )
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), **(extra_env or {})}
    proc = subprocess.run(["bash", "-c", probe, str(SCRIPT), str(env_file), str(env_file)],
                          capture_output=True, text=True, env=env, check=True)
    values = dict(line.split("=", 1) for line in proc.stdout.splitlines())
    return values, Path(f"{env_file}.out").read_text()


def test_loader_exports_allowlisted_keys_and_strips_quotes(tmp_path):
    f = tmp_path / ".env.local"
    f.write_text(
        "LLM_DAILY_CAP=7\n"
        'SEC_USER_AGENT="Personal Investment (me@example.com)"\n'
        "DATABASE_URL='postgresql://u:p@localhost:5432/db'\n"
        "PLAUD_TOKEN=abc=def\n"
        "WORKER_POLL_INTERVAL_SECONDS=3\n"
        "LLM_SINGLE=\"\n"
        "OPENAI_API_KEY=sk-should-not-load\n"
        "# LLM_COMMENTED=1\n"
    )
    values, printed = _load(f)
    assert values["LLM_DAILY_CAP"] == "[7]"
    assert values["SEC_USER_AGENT"] == "[Personal Investment (me@example.com)]"
    assert values["DATABASE_URL"] == "[postgresql://u:p@localhost:5432/db]"
    assert values["PLAUD_TOKEN"] == "[abc=def]"
    assert values["WORKER_POLL_INTERVAL_SECONDS"] == "[3]"
    assert values["LLM_SINGLE"] == '["]'               # 따옴표 한 글자는 벗기지 않는다
    assert values["OPENAI_API_KEY"] == "[UNSET]"       # 허용목록 밖
    assert printed == ""                               # 값을 출력하지 않는다


def test_loader_keeps_existing_env_and_survives_missing_keys(tmp_path):
    f = tmp_path / ".env.local"
    f.write_text("OTHER=1\n")                          # 맞는 줄 없음 → grep 1 이어도 죽지 않는다
    values, _ = _load(f, {"LLM_DAILY_CAP": "12"})
    assert values["LLM_DAILY_CAP"] == "[12]"
    assert values["SEC_USER_AGENT"] == "[UNSET]"

    f.write_text("LLM_DAILY_CAP=7\n")
    values, _ = _load(f, {"LLM_DAILY_CAP": "12"})
    assert values["LLM_DAILY_CAP"] == "[12]"           # 이미 있는 환경이 우선
