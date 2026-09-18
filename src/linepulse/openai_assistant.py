"""VW LLM gateway support for the LinePulse dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx
from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-4o"
IDP_TOKEN_URL = "https://idp.cloud.vwgroup.com/auth/realms/kums-mfa/protocol/openid-connect/token"
LLM_BASE_URL = "https://llmapi.ai.vwgroup.com"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_HISTORY_MESSAGES = 8
MAX_MESSAGE_CHARS = 2_000


class AssistantUnavailableError(RuntimeError):
    """Raised when the optional dashboard assistant cannot answer."""


def _load_environment() -> None:
    """Load local credentials without overwriting explicitly exported values."""

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / "env", override=False)


def is_configured() -> bool:
    """Return whether the VW gateway credentials are available locally."""

    _load_environment()
    return all(
        os.getenv(name, "").strip()
        for name in ("VW_LLM_CLIENT_ID", "VW_LLM_CLIENT_SECRET", "VW_LLM_API_KEY")
    )


def _credential(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise AssistantUnavailableError(
            "Add VW_LLM_CLIENT_ID, VW_LLM_CLIENT_SECRET, and VW_LLM_API_KEY to .env, "
            "then restart the dashboard."
        )
    return value


def get_token() -> str:
    """Obtain a short-lived CloudIDP token for the VW LLM gateway."""

    try:
        response = httpx.post(
            IDP_TOKEN_URL,
            data={
                "client_id": _credential("VW_LLM_CLIENT_ID"),
                "client_secret": _credential("VW_LLM_CLIENT_SECRET"),
                "grant_type": "client_credentials",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        token = str(response.json().get("access_token", "")).strip()
    except httpx.HTTPStatusError as exc:
        raise AssistantUnavailableError(
            "CloudIDP rejected the configured client credentials."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise AssistantUnavailableError(
            "Could not obtain a CloudIDP access token. Check the corporate network connection."
        ) from exc
    if not token:
        raise AssistantUnavailableError("CloudIDP returned no access token.")
    return token


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


def _instructions(context: Mapping[str, Any]) -> str:
    return """You are LinePulse AI's conversational maintenance-support assistant.
Answer questions about the supplied Class A portfolio and selected asset in clear,
plain language. Explain sensor evidence, trends, alerts, planning horizons, risk,
recommendations, data quality, and the human approval workflow. Treat all data as
synthetic demo data. Never claim a confirmed failure, an OEM safety limit, a true
remaining-useful-life estimate, or a live equipment connection. Do not invent
measurements or evidence that is not in the supplied context. Do not advise an
autonomous shutdown or equipment control action. Make it clear that a qualified
maintenance professional must make the final decision.

Dashboard context (use only this as factual project evidence):
""" + json.dumps(context, default=str, ensure_ascii=False)


def answer_question(
    messages: Sequence[Mapping[str, str]],
    context: Mapping[str, Any],
) -> str:
    """Send a VW LLM chat-completions request using the documented gateway flow."""

    _load_environment()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AssistantUnavailableError(
            "The OpenAI package is not installed. Run the project dependency install."
        ) from exc

    history: list[dict[str, str]] = []
    for message in list(messages)[-MAX_HISTORY_MESSAGES:]:
        role = "assistant" if str(message.get("role", "")).lower() == "assistant" else "user"
        content = str(message.get("content", "")).strip()[:MAX_MESSAGE_CHARS]
        if content:
            history.append({"role": role, "content": content})
    if not history:
        raise ValueError("Ask a question before requesting an assistant response.")

    try:
        client = OpenAI(
            api_key=get_token(),
            base_url=LLM_BASE_URL,
            default_headers={
                "X-LLM-API-CLIENT-ID": f"Bearer {_credential('VW_LLM_API_KEY')}"
            },
        )
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            messages=[{"role": "system", "content": _instructions(context)}, *history],
            temperature=0.0,
        )
        answer = str(response.choices[0].message.content or "").strip()
    except AssistantUnavailableError:
        raise
    except Exception as exc:
        raise AssistantUnavailableError(
            "The VW LLM request failed. Check the credentials, model name, and network connection."
        ) from exc

    if not answer:
        raise AssistantUnavailableError("The VW LLM model returned no text response.")
    return answer
