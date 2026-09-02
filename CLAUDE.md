# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this service is

FastAPI backend (uvicorn on `:8010`, all routes under `/v1`) for firewall/network-config work in the
Defense Halo platform: AI security analysis, cross-vendor translation, an SSE streaming
network-security chat assistant, and live rule ingestion from Cisco FMC. It powers the React
frontend's Config Analyzer / Config Translator tabs — in production nginx in the frontend container
proxies `/analyzer/` here, so the browser hits `/analyzer/v1/...`. The API itself has **no
authentication**; only outbound calls authenticate (Keycloak → vLLM, per-request credentials → FMC).

`API.md` is the maintained API reference for every endpoint — update it when you change the API
surface.

## Commands

- Run locally: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`,
  then `uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload`
- Interactive docs: `http://localhost:8010/docs`
- Container: `docker build -t config-analyzer-backend .`
- No test suite or Python linter is configured.
- CI lints Markdown/YAML on every pipeline (configs vendored as `.markdownlint.json` /
  `.yamllint.yml`). Verify before pushing:
  `npx -y markdownlint-cli2@0.22.1 --fix "**/*.md" "#node_modules"` and `yamllint .`

Note: `README.md` references `dev.sh` and `.env.example`, but neither file exists — use the manual
setup above and a hand-written `.env`.

## Git workflow

Never commit directly to `main` or `dev`. Branch off as `feat-short-name` (kebab-case with a
**hyphen**, never a slash — `feat/x` breaks the CI build) and open a merge request into `dev`.

## Architecture

Request flow is strictly layered: `app/api/v1/endpoints/*` (thin FastAPI routers) →
`app/services/*` (business logic + prompt assembly) → `app/services/vllm_service.py` (async
wrappers) → `app/services/llm_interface.py` (`vLLMClient` + `KeycloakTokenManager`). Prompt
templates live in `app/prompts/`, settings in `app/core/config.py`.

### LLM plumbing — the part everything depends on

- `app/core/config.py` (`pydantic-settings`, reads `.env`): `VLLM_ENDPOINT`/`VLLM_MODEL` plus
  Keycloak (`LLM_AUTH_URL`, `LLM_CLIENT_ID`, `LLM_CLIENT_SECRET`) and runtime knobs
  (`LLM_CHAT_TIMEOUT`, `LLM_NUM_CTX`, `LLM_SSL_VERIFY`, `LLM_ENABLE_THINKING`).
- `vllm_service.py` builds a **singleton `vLLMClient` at import time and raises if the three
  Keycloak vars are unset** — the app fails fast at startup with no static-token fallback. Keep it
  that way (this mirrors the Keycloak-only auth decision shared with the `backend/` repo).
- `vLLMClient.get_chat_completion` is **synchronous** (`requests`, 3 retries with exponential
  backoff); `call_vllm_api` runs it through `run_in_executor` so the event loop never blocks. The
  streaming path (`get_chat_completion_stream` / `stream_vllm_api`) is separately implemented with
  async `httpx` and parses vLLM's SSE lines. `KeycloakTokenManager` is a per-`(auth_url, client_id)`
  singleton that caches/refreshes client-credentials tokens.
- New LLM calls should go through `call_vllm_api` / `stream_vllm_api`, not a new HTTP client.

### The four features

- **Analysis** (`POST /v1/configs/analyze` → `analysis_service.py`): concatenates uploaded files
  (each prefixed `--- File: <name> ---`), truncates at 400,000 chars, single LLM call. The prompt
  (`analysis_prompts.ANALYZE_CONFIG_PROMPT`) demands a JSON object with `file_metadata` and `issues`
  keys; the response's `analysis` field is the **raw LLM string** — the frontend parses it, this
  service does not validate it.
- **Translation** (`POST /v1/configs/translate` → `translation_service.py`): single LLM call using
  `TRANSLATE_CONFIG_PROMPT`, parameterized by `target_vendor` (the frontend sends e.g.
  `"Juniper Junos"`, `"Palo Alto PAN-OS"`). Vendor-specific syntax guidance lives in
  `translation_prompts.VENDOR_RULES`, matched case-insensitively by substring via
  `get_vendor_rules()` — currently only Juniper has tuned rules; add new vendors there, not in the
  base template.
- **Chat** (`POST /v1/chat/stream` → `chat_service.py`): two LLM calls per message. First a
  guardrail classifier (temperature 0, 10 tokens, ALLOWED/DENIED; **fails open**), then the streamed
  answer as SSE `data: {"content": ...}` frames. The system prompt is built from frontend-supplied
  `context` (`active_tab`, `config_content` capped at 15k chars, `selected_issue`, `all_issues`,
  `history`). History is normalized into strict system → user → assistant → user alternation
  (same-role messages merged, leading assistant dropped) because vLLM rejects non-alternating
  message lists — preserve this if you touch message assembly.
- **Fetch** (`POST /v1/fetch/{policies,rules,test-connection}` → `app/services/factory.py`):
  provider-factory pattern. `BaseFirewallProvider` (`app/core/providers/base.py`) defines the
  vendor-agnostic async interface; `FmcProvider` (`app/services/firewall/fmc_service.py`, Cisco
  Firepower Management Center) is the only registered implementation — Fortinet/Juniper are
  commented-out stubs. To add a vendor: subclass `BaseFirewallProvider`, register it in
  `FirewallProviderFactory._providers`. Providers receive host/username/password **per request**
  (nothing stored); `normalize_rules_for_ai` flattens vendor JSON into compact text for the LLM.
  `app/models/firewall.py` holds standardized Pydantic models for cross-vendor rule mapping.
