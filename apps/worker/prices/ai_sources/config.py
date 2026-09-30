"""AI Key Data 로스터·엔드포인트 — 사람이 고치는 곳은 여기 한 군데다."""
from __future__ import annotations

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── npm ──────────────────────────────────────────────────────────────────────
NPM_RANGE = "https://api.npmjs.org/downloads/range"
# 코딩 에이전트 CLI 13종(드라이브 `sources.toml` 로스터 계열). 2026-09-27 전부 200 확인.
NPM_CLI_PACKAGES: list[tuple[str, str]] = [
    ("@anthropic-ai/claude-code", "Claude Code"),
    ("@openai/codex", "Codex CLI"),
    ("@anthropic-ai/claude-agent-sdk", "Claude Agent SDK"),
    ("opencode-ai", "opencode"),
    ("@github/copilot", "GitHub Copilot CLI"),
    ("@google/gemini-cli", "Gemini CLI"),
    ("@qwen-code/qwen-code", "Qwen Code"),
    ("cline", "Cline CLI"),
    ("@kilocode/cli", "Kilo Code CLI"),
    ("@augmentcode/auggie", "Auggie"),
    ("@sourcegraph/amp", "Amp"),
    ("@charmland/crush", "Crush"),
    ("@factory/cli", "Factory Droid"),
]
# 기존 `/market/ai-data` 의 SDK 6종 — 두 번째 그룹으로 같이 본다.
NPM_SDK_PACKAGES: list[tuple[str, str]] = [
    ("openai", "OpenAI"),
    ("@anthropic-ai/sdk", "Anthropic"),
    ("@google/genai", "Google"),
    ("ai", "Vercel AI SDK"),
    ("langchain", "LangChain"),
    ("@huggingface/inference", "HuggingFace"),
]
# npm range 한 번에 받을 수 있는 최대 폭은 18개월이다.
NPM_MAX_DAYS = 540
NPM_SCOPED_PACING_SECONDS = 0.3

# ── Ramp AI Index ────────────────────────────────────────────────────────────
RAMP_URL = "https://ramp.com/data/ai-index"

# ── OpenRouter ───────────────────────────────────────────────────────────────
OPENROUTER_RANKINGS = "https://openrouter.ai/api/v1/datasets/rankings-daily"
OPENROUTER_FLOOR = "2025-01-01"  # 데이터셋 시작일(API 문서) — 이보다 앞은 400/클램프
OPENROUTER_CHUNK_DAYS = 90
OPENROUTER_ATTRIBUTION = "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}. CC BY 4.0"

# ── VS Code Marketplace ──────────────────────────────────────────────────────
VSCODE_QUERY = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
VSCODE_API_VERSION = "7.2-preview.1"
VSCODE_FLAGS = 914
# publisher.extensionName — 2026-09-27 extensionquery 로 전부 존재 확인.
VSCODE_EXTENSIONS: list[tuple[str, str]] = [
    ("GitHub.copilot-chat", "GitHub Copilot Chat"),
    ("anthropic.claude-code", "Claude Code"),
    ("openai.chatgpt", "Codex (OpenAI)"),
    ("saoudrizwan.claude-dev", "Cline"),
    ("RooVeterinaryInc.roo-cline", "Roo Code"),
    ("kilocode.Kilo-Code", "Kilo Code"),
    ("Google.geminicodeassist", "Gemini Code Assist"),
    ("Continue.continue", "Continue"),
]

# ── PyPI (pypistats) ─────────────────────────────────────────────────────────
PYPI_RECENT = "https://pypistats.org/api/packages/{package}/recent"
PYPI_PACING_SECONDS = 3.0
PYPI_MAX_429 = 3
PYPI_PACKAGES: list[tuple[str, str]] = [
    ("anthropic", "Anthropic SDK"),
    ("openai", "OpenAI SDK"),
    ("langchain", "LangChain"),
    ("claude-agent-sdk", "Claude Agent SDK"),
    ("openai-agents", "OpenAI Agents SDK"),
]

# ── Epoch AI ─────────────────────────────────────────────────────────────────
# zip URL → 쓰는 멤버 CSV. 나머지 멤버는 읽지 않는다.
EPOCH_DATASETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ai_companies": (
        "https://epoch.ai/data/ai_companies.zip",
        ("ai_companies_revenue_reports.csv", "ai_companies_funding_rounds.csv"),
    ),
    "ai_chip_sales": (
        "https://epoch.ai/data/ai_chip_sales.zip",
        ("timelines_by_chip.csv", "chip_types.csv"),
    ),
    "data_centers": (
        "https://epoch.ai/data/data_centers/data_centers.zip",
        ("data_centers.csv", "data_center_timelines.csv"),
    ),
}
EPOCH_SHRINK_FLOOR = 0.5  # 행수가 이전의 50% 미만으로 줄면 실패로 본다
EPOCH_ATTRIBUTION = "Epoch AI (epoch.ai/data), CC BY 4.0"
