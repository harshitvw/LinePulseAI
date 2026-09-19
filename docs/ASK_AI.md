Ask AI guide

Purpose

Ask AI is a conversational maintenance-support workspace in the LinePulse dashboard. It helps users understand the selected Class A asset's visible risk status, evidence, planning horizon, recommended action, and maintenance workflow. It is decision support only: it cannot control equipment or replace a qualified maintenance decision.

What users can do

Ask why the selected asset is red, amber, or green.

Ask about visible sensor evidence, trends, risk, planning horizon, or the recommended action.

Ask how a technician or Equipment Owner should use the human approval and outcome-verification workflow.

Continue a short conversation about the currently selected asset.

Clear the local browser-session conversation with Clear chat.

The assistant is given the selected asset's dashboard-visible evidence and a compact portfolio summary. It is not given local files, credentials, hidden data, or equipment-control access.

Safe operating boundaries

All current LinePulse data is synthetic demo data.

The assistant must not present a failure hypothesis as confirmed, claim a live equipment connection, or claim an OEM safety limit or validated remaining-useful-life prediction.

It must not invent measurements or evidence outside the supplied dashboard context.

It must not recommend autonomous shutdowns or write to equipment.

A qualified maintenance professional remains the final decision-maker.

Configuration

Ask AI calls the VW LLM gateway. Store credentials only in the local, git-ignored .env file:

VW_LLM_CLIENT_ID=your_cloudidp_client_id
VW_LLM_CLIENT_SECRET=your_cloudidp_client_secret
VW_LLM_API_KEY=your_vw_virtual_key
OPENAI_MODEL=gpt-4o

Do not create or distribute a populated file named env; the repository ignores .env, not env. Before packaging the submission, search the project for VW_LLM_, remove any populated credential file, and rotate any secret that has entered a ZIP, chat, email, screenshot, ticket, or Git commit.

Ask AI is a bounded conversational component, not an autonomous maintenance agent. It performs no tool selection, database write, decision submission, equipment action, or background task.

Request flow

For each Ask AI request, the application:

Sends the CloudIDP client ID and client secret to the VW token endpoint using the client-credentials grant.

Receives a short-lived access token.

Creates an OpenAI-compatible client with the VW base URL, access token, and X-LLM-API-CLIENT-ID virtual-key header.

Calls chat.completions.create with gpt-4o by default, the assistant's safety instructions, selected-asset context, and recent conversation messages.

Displays the returned answer in the Ask AI conversation.

If any of these steps fail, the application reports the assistant error and leaves the deterministic dashboard, risk assessment, human decision, and audit workflow unchanged.

The Chat Completions API uses an ordered list of role-based messages and returns text in the completion choice. See the official OpenAI Chat Completions reference.

Start and verify

Save the credentials in .env.

Restart the Streamlit dashboard.

Open http://127.0.0.1:8501 and choose Ask AI.

Ask: Why is this asset amber?

Confirm that the response refers to the selected asset's visible evidence and retains the human-decision boundary.

For an isolated technical check, run a fixed prompt through linepulse.openai_assistant.answer_question. The project test suite also verifies the CloudIDP request fields, VW header, model call, and context boundary without making live network requests.

Troubleshooting

Message or symptom

What to check

Assistant is not configured

Confirm all three VW_LLM_* variables are present in .env, then restart Streamlit.

CloudIDP rejected credentials

Check the client ID and client secret with the VW platform owner; do not paste them into logs or chat.

VW LLM request failed

Check VPN/network access, virtual key, model access, and the VW gateway service.

Terminal check works but UI fails

Restart Streamlit, hard-refresh the browser with Ctrl+F5, then retry with a new chat message.

Authentication failure after exposure

Rotate the affected credential, update .env, restart Streamlit, and retest.

Files involved

dashboard/app.py — Ask AI navigation, chat interface, and error display.

src/linepulse/openai_assistant.py — CloudIDP token retrieval, VW client construction, safety instructions, and chat request.

tests/test_openai_assistant.py — offline unit tests for credential flow and context handling.