"""Standard OpenAI Responses API support for the LinePulse dashboard."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-5-mini"
MAX_HISTORY_MESSAGES = 8
MAX_MESSAGE_CHARS = 2_000


class AssistantUnavailableError(RuntimeError):
    """Raised when the optional dashboard assistant cannot answer."""


def _load_environment() -> None:
    """Load local credentials without overwriting explicitly exported values."""

    load_dotenv(override=False)


def is_configured() -> bool:
    """Return whether the standard OpenAI API key is available locally."""

    _load_environment()
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def build_assistant_context(
    portfolio_summary: Mapping[str, Any], selected_asset: Mapping[str, Any]
) -> dict[str, Any]:
    """Limit model context to dashboard-visible portfolio and asset evidence."""

    evidence = selected_asset.get("evidence_passport", [])
    if not isinstance(evidence, list):
        evidence = []
    return {
        "portfolio": {
            "class_a_assets": portfolio_summary.get("total_assets"),
            "status_counts": portfolio_summary.get("status_counts"),
            "scope": "Synthetic Class A maintenance decision-support prototype",
        },
        "selected_asset": {
            "asset_id": selected_asset.get("asset_id"),
            "name": selected_asset.get("name"),
            "asset_type": selected_asset.get("type")
            or selected_asset.get("asset_type"),
            "line": selected_asset.get("line"),
            "status": selected_asset.get("status"),
            "technical_risk": selected_asset.get("technical_risk"),
            "attention_priority": selected_asset.get("attention_priority"),
            "planning_horizon_days": selected_asset.get("days_remaining"),
            "failure_mode_hypothesis": selected_asset.get("failure_mode"),
            "recommended_action": selected_asset.get("recommended_action"),
            "data_quality_flags": selected_asset.get("data_quality_flags", []),
            "evidence_passport": evidence[:3],
        },
    }


def _instructions() -> str:
    return """You are LinePulse AI's conversational maintenance-support assistant.
Answer questions about the supplied Class A portfolio and selected asset in clear,
plain language. Explain sensor evidence, trends, alerts, planning horizons, risk,
recommendations, data quality, and the human approval workflow. Treat all data as
synthetic demo data. Never claim a confirmed failure, an OEM safety limit, a true
remaining-useful-life estimate, or a live equipment connection. Do not invent
measurements or evidence that is not in the supplied context. Do not advise an
autonomous shutdown or equipment control action. Make it clear that a qualified
maintenance professional must make the final decision."""


def answer_question(
    messages: Sequence[Mapping[str, str]],
    context: Mapping[str, Any],
) -> str:
    """Send a standard OpenAI Responses API request using OPENAI_API_KEY."""

    _load_environment()
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise AssistantUnavailableError(
            "Add OPENAI_API_KEY to .env, then restart the dashboard."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AssistantUnavailableError(
            "The OpenAI package is not installed. Run the project dependency install."
        ) from exc

    history = []
    for message in list(messages)[-MAX_HISTORY_MESSAGES:]:
        role = (
            "Assistant"
            if str(message.get("role", "")).lower() == "assistant"
            else "User"
        )
        content = str(message.get("content", "")).strip()[:MAX_MESSAGE_CHARS]
        if content:
            history.append(f"{role}: {content}")
    if not history:
        raise ValueError("Ask a question before requesting an assistant response.")

    prompt = (
        "Dashboard context (use only this as factual project evidence):\n"
        + json.dumps(context, default=str, ensure_ascii=False)
        + "\n\nConversation:\n"
        + "\n".join(history)
    )
    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        client = OpenAI(
            base_url="https://llmapi.ai.vwgroup.com",
            api_key=api_key,
        )
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            instructions=_instructions(),
            input=prompt,
            max_output_tokens=500,
        )
    except Exception as exc:
        raise AssistantUnavailableError(
            "The OpenAI request failed. Check the API key, model name, and network connection."
        ) from exc

    answer = str(getattr(response, "output_text", "")).strip()
    if not answer:
        raise AssistantUnavailableError("The OpenAI model returned no text response.")
    return answer
