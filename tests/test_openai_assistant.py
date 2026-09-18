from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from linepulse.openai_assistant import answer_question, build_assistant_context, is_configured


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

    def test_standard_openai_client_uses_environment_api_key(self) -> None:
        response = Mock(output_text="Inspect the vibration trend before scheduling work.")
        client = Mock()
        client.responses.create.return_value = response
        with patch("linepulse.openai_assistant._load_environment"), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "standard-api-key", "OPENAI_MODEL": "gpt-5-mini"},
            clear=True,
        ), patch("openai.OpenAI", return_value=client) as openai_client:
            answer = answer_question(
                [{"role": "user", "content": "What should I inspect first?"}],
                {"portfolio": {}, "selected_asset": {"asset_id": "A001"}},
            )

        self.assertEqual(answer, "Inspect the vibration trend before scheduling work.")
        openai_client.assert_called_once_with(
            base_url="https://llmapi.ai.vwgroup.com",
            api_key="standard-api-key",
        )
        self.assertEqual(client.responses.create.call_args.kwargs["model"], "gpt-5-mini")

    def test_configuration_requires_standard_openai_api_key(self) -> None:
        with patch("linepulse.openai_assistant._load_environment"), patch.dict(
            os.environ, {"OPENAI_API_KEY": "key"}, clear=True
        ):
            self.assertTrue(is_configured())
