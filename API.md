# Config Analyzer Backend — API Reference

FastAPI service for firewall/network-configuration work in the Defense Halo platform:
AI security analysis, cross-vendor translation, a streaming network-security chat
assistant, and live rule ingestion from Cisco Firepower Management Center (FMC).

- **Server:** uvicorn on `0.0.0.0:8010` (see [Configuration](#configuration))
- **Base path:** all routes are mounted under `/v1`
- **Interactive docs:** FastAPI auto-generates `GET /docs` (Swagger UI), `GET /redoc`, and `GET /openapi.json`
- **CORS:** wide open (`allow_origins=["*"]`, all methods/headers, credentials allowed)
- **Auth:** the API itself has **no authentication**. Outbound calls authenticate to the vLLM endpoint (Keycloak) and to Cisco FMC (per-request credentials supplied by the caller).

> **Production routing:** the React dashboard never calls this service directly. nginx in
> the frontend container proxies `/analyzer/` → this service (`CONFIG_ANALYZER_URL`), so a
> browser request to `/analyzer/v1/configs/analyze` reaches `POST /v1/configs/analyze` here.

## Endpoint summary

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/v1/health` | Service liveness + upstream vLLM reachability |
| POST | `/v1/configs/analyze` | AI security analysis of uploaded config files |
| POST | `/v1/configs/translate` | AI cross-vendor translation of a config file |
| POST | `/v1/chat/stream` | SSE streaming network-security chat assistant |
| POST | `/v1/fetch/policies` | List access-control policies from a firewall manager (Cisco FMC) |
| POST | `/v1/fetch/rules` | Fetch + normalize all rules of one policy for AI analysis |
| POST | `/v1/fetch/test-connection` | Verify firewall-manager connectivity/credentials |

---

## GET /v1/health

Liveness check. Also verifies the upstream vLLM inference server by sending an
authenticated 1-token "ping" chat completion through the normal LLM client
(so a `200` with `"ai_server": "online"` proves Keycloak auth and the vLLM endpoint
both work end to end).

**Request:** no parameters.

**Response `200`** (always `200`; only `ai_server` varies):

```json
{ "status": "ok", "ai_server": "online" }
```

```json
{ "status": "ok", "ai_server": "offline" }
```

Note: because the ping is a real LLM round-trip (with up to 3 retries and exponential
backoff inside the client), this endpoint can be slow when the vLLM endpoint is down.

---

## POST /v1/configs/analyze

Deep AI security analysis of one or more configuration files against a chosen
framework. Powers the frontend's **Config Analyzer** tab.

**Request:** `multipart/form-data`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `files` | file upload, repeatable (`List[UploadFile]`) | yes | One or more raw config files. Decoded as UTF-8 with latin-1 fallback. |
| `framework` | form string | no (default `"Default Best Practices"`) | Analysis framework name interpolated into the LLM prompt (e.g. CIS, NIST). |

Processing: all files are concatenated (each prefixed with `--- File: <name> ---`),
truncated to **400,000 characters** if larger, and sent to the vLLM endpoint in a single
prompt (`temperature=0.1`, `max_tokens=8192`).

**Response `200` — success:**

```json
{
  "status": "completed",
  "analysis": "{ \"file_metadata\": [...], \"issues\": [...] }"
}
```

`analysis` is a **string** containing the raw LLM output. The prompt instructs the model
to emit a single JSON object (no markdown fences) with this shape, which the frontend
parses:

```json
{
  "file_metadata": [
    { "file": "asa-fw01.txt", "vendor": "Cisco", "os": "ASA", "version": "9.12(4)" }
  ],
  "issues": [
    {
      "id": "vuln-001",
      "severity": "High",
      "title": "Permissive Any-Any Rule Detected",
      "description": "A firewall rule was found that allows any traffic from any source to any destination.",
      "file": "asa-fw01.txt",
      "line": 10,
      "originalCode": "access-list OUTSIDE_IN extended permit ip any any",
      "proposedCode": "access-list OUTSIDE_IN extended permit ip 10.0.0.0 255.0.0.0 192.168.1.0 255.255.255.0",
      "strategy": "Restrict the rule to only allow necessary traffic."
    }
  ]
}
```

`severity` is one of `"High"`, `"Medium"`, `"Low"`. Since the payload is LLM-generated,
callers should parse defensively.

**Response `200` — LLM failure** (note: errors are reported in-band with HTTP 200):

```json
{ "status": "error", "message": "<exception> | Details: <upstream body if any>" }
```

**Error responses:**
- `400` — `{"detail": "No files provided"}` (empty file list)
- `422` — FastAPI validation error when the `files` part is missing entirely

---

## POST /v1/configs/translate

Translates a single configuration file to another vendor's syntax. Powers the
frontend's **Config Translator** tab.

**Request:** `multipart/form-data`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `file` | file upload (single `UploadFile`) | yes | Source configuration. UTF-8 with latin-1 fallback. |
| `target_vendor` | form string | yes | Desired target vendor. |

> Implementation note: `target_vendor` is accepted and passed to the prompt formatter,
> but the current prompt template (`app/prompts/translation_prompts.py`) is hardcoded
> for **Cisco ASA → Juniper Junos (SRX) `set` commands** and does not interpolate
> `target_vendor`. Other targets will still produce Junos output until the prompt is
> generalized.

LLM call parameters: `temperature=0.1`, `max_tokens=8192`.

**Response `200` — success:**

```json
{
  "status": "completed",
  "translated_config": "set security zones security-zone outside interfaces ge-0/0/0.0\nset security address-book global address WEB-SRV 192.168.1.10/32\n..."
}
```

**Response `200` — LLM failure:**

```json
{ "status": "error", "message": "<exception> | Details: <upstream body if any>" }
```

**Error responses:**
- `422` — validation error when `file` or `target_vendor` is missing

---

## POST /v1/chat/stream

Server-Sent Events (SSE) endpoint for the network-security chat assistant
(`ChatWidget` in the frontend). The assistant is scoped to network security /
firewall topics: an LLM-based **input guardrail** classifies each message first and
refuses requests for general-purpose source code or malicious content. The system
prompt also instructs the model to redact secrets found in configs and to only ever
emit network-device CLI (never general programming code).

**Request:** `application/json`

```json
{
  "message": "How do I fix ISSUE-01?",
  "context": {
    "active_tab": "analyzer",
    "config_content": "...raw config text...",
    "selected_issue": {
      "displayId": "ISSUE-01",
      "title": "Permissive Any-Any Rule Detected",
      "severity": "High",
      "description": "...",
      "originalCode": "access-list OUTSIDE_IN extended permit ip any any"
    },
    "all_issues": [
      { "displayId": "ISSUE-01", "title": "Permissive Any-Any Rule Detected", "severity": "High" }
    ],
    "history": [
      { "sender": "user", "text": "Hi" },
      { "sender": "ai", "text": "Hello! How can I help with your network audit?" }
    ]
  }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `message` | string | yes | The user's chat message. |
| `context` | object | no (default `{}`) | Free-form dict; recognized keys below. |
| `context.active_tab` | string | no | `"analyzer"`, `"translate"`, or `"greenfield"` — selects the context description given to the model. Anything else → generic "browsing the dashboard". |
| `context.config_content` | string | no | Active config file content; first **15,000 characters** are injected into the system prompt. |
| `context.selected_issue` | object | no | Currently selected finding: `displayId`, `title`, `severity`, `description`, `originalCode`. |
| `context.all_issues` | array of objects | no | Audit findings summary; each uses `displayId`, `title`, `severity`. |
| `context.history` | array of objects | no | Prior turns: `{ "sender": "ai" \| "user", "text": "..." }`. Empty texts are dropped; consecutive same-role messages are merged; the sequence is normalized to strict user/assistant alternation starting with a user turn (a vLLM requirement). |

LLM call parameters: `temperature=0.2`, `max_tokens=1024`.

**Response:** `200` with `Content-Type: text/event-stream`.

### Stream framing

Every event is a bare `data:` line carrying a JSON object with a single `content`
key (a text fragment). There are **no `event:` names, no `id:` fields, and no
`[DONE]` sentinel** sent to the client:

```
data: {"content": "To remediate "}

data: {"content": "ISSUE-01, replace the any-any rule with..."}

```

Clients should concatenate `content` values in order. The stream **terminates by the
server closing the HTTP response** when the upstream LLM stream finishes — detect
end-of-stream via connection close (e.g. the `fetch` reader reporting `done`), not via
a sentinel event.

Special single-event cases (each is one `data:` frame followed by stream close):

- **Guardrail denial** — content begins with
  `⛔ **Request Denied by Security Guardrail.**` (the guardrail is fail-open: if the
  guardrail LLM call itself errors, the message is allowed through).
- **Mid-stream LLM error** — content begins with `⚠️ **AI Stream Error**: ...`.

Note: guardrail denials and stream errors are delivered as normal `data:` events with
HTTP 200 — clients cannot distinguish them from model output except by content.

---

## POST /v1/fetch/* — live rule ingestion from firewall managers

All three endpoints share one JSON request model (`FetchConfigRequest`) and a
vendor-provider factory. Only `"cisco"` (Firepower Management Center) is implemented
today; Fortinet/Juniper are stubbed out in `app/services/factory.py`.

**Shared request body** (`application/json`):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `vendor` | string | yes | Provider selector, case-insensitive. Currently only `"cisco"`. |
| `host` | string | yes | FMC hostname or URL. `https://` is prefixed automatically if no scheme is given. |
| `username` | string | yes | FMC API username (sent per-request; never stored). |
| `password` | string | yes | FMC API password (sent per-request; never stored). |
| `verify_ssl` | boolean | no (default `false`) | Verify the FMC TLS certificate. |
| `policy_id` | string | no | Required by `/v1/fetch/rules` only. |

An unsupported `vendor` raises `ValueError` in the factory — surfaced as `400` from
`/policies`, `500` from `/rules`, and a `200 {"status":"error"}` from `/test-connection`.

### POST /v1/fetch/policies

Lists the access-control policies available on the manager.

**Response `200`:**

```json
{
  "status": "success",
  "policies": [
    {
      "id": "005056A1-4F3B-0ed3-0000-004294969529",
      "name": "Corp-Access-Policy",
      "type": "AccessPolicy",
      "links": { "self": "https://fmc.example.net/api/fmc_config/v1/domain/.../accesspolicies/..." }
    }
  ]
}
```

`policies` is the raw `items` array from the FMC API (vendor-shaped, not normalized).

**Errors:** `400` (unsupported vendor), `500` `{"detail": "Failed to fetch policies: <reason>"}`
(auth failure, connectivity, FMC API errors).

### POST /v1/fetch/rules

Fetches **all** access rules of one policy (paginated internally, `expanded=true`) and
normalizes them into a text block suitable for feeding to `/v1/configs/analyze`-style
AI analysis.

`policy_id` is required — missing it returns
`400 {"detail": "policy_id is required to fetch rules"}`.

**Response `200`:**

```json
{
  "status": "success",
  "policy_id": "005056A1-4F3B-0ed3-0000-004294969529",
  "rule_count": 42,
  "normalized_configuration": "Rule: Allow-Web-Out (Enabled: True)\n  Action: ALLOW\n  Source: ['Inside-Net']\n  Destination: 'Any'\n  Ports: ['HTTPS']\n  Logging: Begin=False, End=True\n  Inspection: IPS=Balanced-Security, File=None\n"
}
```

Each rule in `normalized_configuration` includes name, enabled flag, action,
source/destination network object names, destination ports, logging begin/end, and
IPS/file inspection policy names.

**Errors:** `500` `{"detail": "Failed to fetch rules: <reason>"}` (also covers
unsupported vendor and auth failures).

### POST /v1/fetch/test-connection

Verifies connectivity and credentials by performing the FMC token authentication.
**Always returns HTTP `200`**; the outcome is in the body:

```json
{ "status": "success", "message": "Connection established successfully" }
```

```json
{ "status": "error", "message": "Connection failed: <reason>" }
```

---

## External services

### vLLM inference endpoint (OpenAI-compatible)

All AI features (analyze, translate, chat, guardrail, health ping) go through a single
`vLLMClient` (`app/services/llm_interface.py`) pointed at an OpenAI-style
`/v1/chat/completions` endpoint:

- **Endpoint / model:** `VLLM_ENDPOINT`, `VLLM_MODEL` env vars.
- **Auth — Keycloak client-credentials, required.** The service **fails at startup**
  (import time) if `LLM_AUTH_URL`, `LLM_CLIENT_ID`, or `LLM_CLIENT_SECRET` is unset —
  there is no static-token fallback in this service. A singleton
  `KeycloakTokenManager` POSTs `grant_type=client_credentials` to `LLM_AUTH_URL`,
  caches the `access_token`, and refreshes it 60 seconds before expiry. Each vLLM
  request carries `Authorization: Bearer <token>`.
- **Resilience:** non-streaming calls retry up to 3 times with exponential backoff
  (2s/4s/8s) and run in a thread executor to keep the event loop free. Streaming calls
  use `httpx` and parse the upstream `data: ... [DONE]` SSE frames into plain content
  chunks.
- **TLS / timeouts:** governed by `LLM_SSL_VERIFY` and `LLM_CHAT_TIMEOUT`.

### Cisco Firepower Management Center (FMC) REST API

Used by the `/v1/fetch/*` endpoints (`app/services/firewall/fmc_service.py`).
Credentials come from the request body on every call — nothing is read from env vars
and no tokens are persisted between requests.

**Auth flow:** `POST {host}/api/fmc_platform/v1/auth/generatetoken` with HTTP Basic
auth; the session token is read from the `X-auth-access-token` response header and the
domain UUID from the `DOMAIN_UUID` header. Subsequent calls send the token in an
`X-auth-access-token` request header.

**FMC endpoints hit:**

| FMC endpoint | Used by |
|--------------|---------|
| `POST /api/fmc_platform/v1/auth/generatetoken` | all (auth), `/v1/fetch/test-connection` |
| `GET /api/fmc_config/v1/domain/{domain_uuid}/policy/accesspolicies` | `/v1/fetch/policies` |
| `GET /api/fmc_config/v1/domain/{domain_uuid}/policy/accesspolicies/{policy_id}/accessrules?expanded=true&offset=…&limit=1000` (paginated until `paging.next` is absent) | `/v1/fetch/rules` |
| `GET /api/fmc_config/v1/domain/{domain_uuid}/object/networkobjects` | provider method exists; not exposed by any route yet |
| `GET /api/fmc_config/v1/domain/{domain_uuid}/object/protocolportobjects` | provider method exists; not exposed by any route yet |

---

## Configuration

Settings load via `pydantic-settings` (`app/core/config.py`) from the environment or a
`.env` file. Names and meanings only — never commit values.

| Variable | Meaning |
|----------|---------|
| `VLLM_ENDPOINT` | Full URL of the OpenAI-compatible chat-completions endpoint. |
| `VLLM_MODEL` | Model name sent in each chat-completion payload. |
| `LLM_AUTH_URL` | Keycloak token endpoint for client-credentials auth. **Required** — startup fails if empty. |
| `LLM_CLIENT_ID` | Keycloak client ID. **Required.** |
| `LLM_CLIENT_SECRET` | Keycloak client secret. **Required.** |
| `LLM_CHAT_TIMEOUT` | Per-request LLM timeout in seconds (default 300). |
| `LLM_NUM_CTX` | Default `max_tokens` when a caller doesn't specify one (default 8192). |
| `LLM_SSL_VERIFY` | Verify TLS on Keycloak/vLLM calls (default false). |
| `LLM_ENABLE_THINKING` | If true, sends `chat_template_kwargs: {"enable_thinking": true}` with each LLM request (default false). |
| `CONCURRENT_REQUESTS` | Declared concurrency limit setting (default 5; not currently referenced by request paths). |
| `CHUNK_SIZE` | Declared chunking size setting (default 100000; chunking helper exists but the analysis path truncates at 400k chars instead). |
| `HOST` / `PORT` | Bind address/port settings (defaults `0.0.0.0` / `8010`). Note: the Dockerfile `CMD` hardcodes `--host 0.0.0.0 --port 8010`, so in-container these env vars are informational. |

No Redis or Kafka — this service is stateless; every request is self-contained.
