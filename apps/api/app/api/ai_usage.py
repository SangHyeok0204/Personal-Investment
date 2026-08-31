from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

from app.core.config import settings
from app.schemas import AiUsageAccountOut, AiUsageMeterOut, AiUsageOut

router = APIRouter(prefix="/api/v1/ai-token-usage", tags=["ai-usage"])

# Snapshot older than this (or missing captured_at) is flagged stale.
STALE_AFTER_SECONDS = 1800


def _parse_captured_at(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_account(raw: dict, *, has_plan: bool) -> AiUsageAccountOut:
    captured_at = _parse_captured_at(raw.get("captured_at"))
    age_seconds = (
        (datetime.now(timezone.utc) - captured_at).total_seconds() if captured_at else None
    )
    stale = captured_at is None or age_seconds > STALE_AFTER_SECONDS

    items = [
        AiUsageMeterOut(
            label=item["label"],
            subtitle=item.get("subtitle"),
            pct=item.get("pct"),
            remaining_pct=item.get("remaining_pct"),
        )
        for item in raw.get("items", [])
    ]

    return AiUsageAccountOut(
        account_num=raw["account_num"],
        email=raw.get("email"),
        plan=raw.get("plan") if has_plan else None,
        captured_at=raw.get("captured_at"),
        age_seconds=age_seconds,
        stale=stale,
        extra_usage_enabled=raw.get("extra_usage_enabled"),
        items=items,
    )


@router.get("", response_model=AiUsageOut)
def get_ai_token_usage() -> AiUsageOut:
    """Proxy the AI usage monitor. Degrades to reachable=false on any upstream failure
    (connect/timeout/HTTP status/malformed JSON) instead of raising, so the dashboard
    can render a stale/unreachable state rather than erroring out."""
    base_url = settings.AI_USAGE_MONITOR_BASE_URL
    fetched_at = datetime.now(timezone.utc).isoformat()

    try:
        with httpx.Client(timeout=8.0) as client:
            claude_resp = client.get(f"{base_url}/api/latest")
            claude_resp.raise_for_status()
            codex_resp = client.get(f"{base_url}/api/latest_codex")
            codex_resp.raise_for_status()
        claude_raw = claude_resp.json()
        codex_raw = codex_resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return AiUsageOut(
            monitor_base_url=base_url,
            reachable=False,
            error=str(exc),
            fetched_at=fetched_at,
            claude=[],
            codex=[],
        )

    return AiUsageOut(
        monitor_base_url=base_url,
        reachable=True,
        error=None,
        fetched_at=fetched_at,
        claude=[_build_account(item, has_plan=True) for item in claude_raw],
        codex=[_build_account(item, has_plan=False) for item in codex_raw],
    )
