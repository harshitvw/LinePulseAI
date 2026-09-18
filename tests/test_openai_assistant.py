from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from linepulse.openai_assistant import answer_question, build_assistant_context, get_token, is_configured


class OpenAiAssistantTests(unittest.TestCase):
    def test_context_contains_only_portfolio_and_selected_asset_evidence(self) -> None:
        context = build_assistant_context(
            {"total_assets": 45, "status_counts": {"RED": 12}},
            {
                "asset_id": "A001",
                "name": "Demo asset",
                "status": "RED",
                "technical_risk": 88.0,
                "evidence_passport": [{"field": "AvgTempC"}] * 4,
                "internal_secret": "must not be sent",
            },
        )

        self.assertEqual(context["portfolio"]["class_a_assets"], 45)
        self.assertEqual(context["selected_asset"]["asset_id"], "A001")
        self.assertEqual(len(context["selected_asset"]["evidence_passport"]), 3)
        self.assertNotIn("internal_secret", context["selected_asset"])

    def test_cloud_idp_token_request_uses_client_credentials(self) -> None:
        response = Mock()
        response.json.return_value = {"access_token": "short-lived-token"}
        with patch.dict(
            os.environ,
            {
                "VW_LLM_CLIENT_ID": "client-id",
                "VW_LLM_CLIENT_SECRET": "client-secret",
                "VW_LLM_API_KEY": "virtual-key",
            },
            clear=True,
        ), patch("linepulse.openai_assistant.httpx.post", return_value=response) as post:
            token = get_token()

        self.assertEqual(token, "short-lived-token")
        response.raise_for_status.assert_called_once()
        self.assertEqual(post.call_args.kwargs["data"]["client_id"], "client-id")
        self.assertEqual(post.call_args.kwargs["data"]["client_secret"], "client-secret")
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "client_credentials")

    def test_vw_client_uses_token_and_api_key_header(self) -> None:
        response = Mock()
        response.choices = [Mock(message=Mock(content="Inspect the vibration trend first."))]
        client = Mock()
        client.chat.completions.create.return_value = response
        with patch("linepulse.openai_assistant._load_environment"), patch(
            "linepulse.openai_assistant.get_token", return_value="short-lived-token"
        ), patch.dict(
            os.environ,
            {
                "VW_LLM_CLIENT_ID": "client-id",
                "VW_LLM_CLIENT_SECRET": "client-secret",
                "VW_LLM_API_KEY": "virtual-key",
                "OPENAI_MODEL": "gpt-4o",
            },
            clear=True,
        ), patch("openai.OpenAI", return_value=client) as openai_client:
            answer = answer_question(
                [{"role": "user", "content": "What should I inspect first?"}],
                {"portfolio": {}, "selected_asset": {"asset_id": "A001"}},
            )

        self.assertEqual(answer, "Inspect the vibration trend first.")
        openai_client.assert_called_once_with(
            base_url="https://llmapi.ai.vwgroup.com",
            api_key="short-lived-token",
            default_headers={"X-LLM-API-CLIENT-ID": "Bearer virtual-key"},
        )
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "gpt-4o")

    def test_configuration_requires_vw_credentials(self) -> None:
        with patch("linepulse.openai_assistant._load_environment"), patch.dict(
            os.environ,
            {
                "VW_LLM_CLIENT_ID": "client-id",
                "VW_LLM_CLIENT_SECRET": "client-secret",
                "VW_LLM_API_KEY": "virtual-key",
            },
            clear=True,
        ):
            self.assertTrue(is_configured())
