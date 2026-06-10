import json
import logging
from typing import Dict, AsyncGenerator, List
from app.services import vllm_service
from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """### ROLE:
You are a highly skilled Network Security Expert and Firewall Audit Assistant. 
While your primary expertise is technical (identifying security gaps and providing CLI recommendations), you should be professional, personable, and helpful in your interactions.

### MANDATORY TECHNICAL RESTRICTIONS:
1. **NO SOURCE CODE GENERATION**: You are strictly FORBIDDEN from generating or providing source code in general programming languages (e.g., Python, C++, Java, JavaScript, Go, Bash, FastAPI, React). If a user technical request requires general-purpose code, you MUST refuse.
2. **DOMAIN FOCUS**: Your technical assistance is limited to network security, firewalls, routing, and the provided configurations. 
3. **SECRET PROTECTION**: NEVER echo plaintext passwords, SNMP strings, or keys found in the config. Replace them with [REDACTED].

### INTERACTION GUIDELINES:
- **GREETINGS**: Respond naturally and politely to greetings (e.g., "Hi", "Hello"). You can introduce yourself or ask how you can help with their network audit today.
- **TONE**: Maintain a professional yet accessible expert persona.
- **CLI ONLY**: The only technical code you are allowed to output is network device CLI syntax (e.g., Cisco IOS, Palo Alto).
- **ISSUES**: If the user mentions an Issue ID (e.g., "ISSUE-01"), reference the 'SUMMARY OF IDENTIFIED FINDINGS' below.

### CONTEXT:
Current Tab: {context_description}

{config_section}
{issue_section}
{all_issues_summary}
"""

async def check_intent_guardrail(message: str, context_desc: str) -> bool:
    """
    Evaluates the user's intent before processing the main request.
    Returns True if the request is ALLOWED, False if it is DENIED.
    """
    guardrail_prompt = f"""You are a strict Input Guardrail for a Network Security application.
Your ONLY job is to classify the user's message as "ALLOWED" or "DENIED".

CURRENT USER CONTEXT: {context_desc}

### DENY RULES (CRITICAL - ONLY DENY IF IT STRICTLY MATCHES THESE):
- The user explicitly asks you to write, generate, or provide source code/scripts in general languages (Python, C++, Java, JavaScript, Bash, Go, FastAPI, React, etc.).
- The user asks for malicious exploits, hacking tutorials, or bypassing security.

### ALLOW RULES (ALLOW ALL OF THESE):
- Casual conversation, greetings, and pleasantries (e.g., "hi", "hello", "thanks", "how are you").
- Asking about network security, firewalls, routing, or explaining network configurations.
- Asking for network CLI commands (Cisco, Palo Alto, Fortinet, etc.).
- Referencing identified vulnerabilities or specific Issue IDs (e.g., "ISSUE-01").
- Conversational follow-ups, clarifications, or ambiguous questions (e.g., "how do I fix it?", "explain more", "upgrade it").

If the message does not explicitly violate the DENY rules, default to ALLOWED.
Output ONLY the word ALLOWED or DENIED."""

    payload = {
        "model": settings.VLLM_MODEL,
        "messages": [
            {"role": "system", "content": guardrail_prompt},
            {"role": "user", "content": message}
        ],
        "temperature": 0.0, # Zero creativity, perfectly deterministic
        "max_tokens": 10
    }

    try:
        response = await vllm_service.call_vllm_api(payload)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
        logger.debug(f"Guardrail verdict: {content!r}")
        if "DENIED" in content:
            return False
        return True
    except Exception as e:
        logger.error(f"Guardrail evaluation failed: {e}")
        return True  # Fallback to allowing it through if the check fails

def get_context_description(context: Dict) -> str:
    active_tab = context.get("active_tab", "analyzer")
    if active_tab == "analyzer":
        return "The user is in the 'Security Audit' tab, reviewing vulnerabilities."
    elif active_tab == "translate":
        return "The user is in the 'Cross-Vendor Translation' tab, converting rules."
    elif active_tab == "greenfield":
        return "The user is in the 'Policy Generator' tab, building new policies."
    return "The user is browsing the dashboard."

async def stream_chat_response(message: str, context: Dict) -> AsyncGenerator[str, None]:
    """
    Handles a chat request and streams the AI's response in SSE format.
    """
    context_desc = get_context_description(context)
    
    # 1. RUN INPUT GUARDRAIL PRE-CHECK
    is_allowed = await check_intent_guardrail(message, context_desc)
    if not is_allowed:
        logger.info(f"Guardrail blocked message in context '{context_desc}'")
        error_msg = "⛔ **Request Denied by Security Guardrail.**\n\nI am exclusively a Network Security Audit Engine. I cannot fulfill requests involving general programming (like C++, Python, or FastAPI), out-of-scope trivia, or malicious actions."
        yield f"data: {json.dumps({'content': error_msg})}\n\n"
        return

    logger.debug(f"Guardrail passed — building chat payload (context='{context_desc}')")

    # 2. PROCEED WITH MAIN AI PIPELINE
    config_content = context.get("config_content", "")
    selected_issue = context.get("selected_issue")
    all_issues = context.get("all_issues", [])
    history = context.get("history", [])
    
    # Build System Message
    all_issues_summary = ""
    if all_issues:
        summary_lines = ["### SUMMARY OF IDENTIFIED FINDINGS (Audit Results):"]
        for issue in all_issues:
            summary_lines.append(f"- {issue.get('displayId')}: {issue.get('title')} ({issue.get('severity')})")
        all_issues_summary = "\n".join(summary_lines)

    config_section = f"### ACTIVE CONFIGURATION FILE CONTENT:\n```\n{config_content[:15000]}\n```" if config_content else ""
    
    issue_section = ""
    if selected_issue:
        issue_section = f"""### CURRENTLY SELECTED ISSUE:
ID: {selected_issue.get('displayId')}
Title: {selected_issue.get('title')}
Severity: {selected_issue.get('severity')}
Description: {selected_issue.get('description')}
Snippet: {selected_issue.get('originalCode')}
"""

    full_system_prompt = SYSTEM_PROMPT.format(
        context_description=context_desc,
        config_section=config_section,
        issue_section=issue_section,
        all_issues_summary=all_issues_summary
    )

    # STRICT vLLM MESSAGE FORMATTING
    # 1. Start with system
    final_messages = [{"role": "system", "content": full_system_prompt}]
    
    # 2. Add history (filtering and merging)
    history_to_process = []
    for h in history:
        txt = h.get("text", "").strip()
        if not txt: continue
        role = "assistant" if h.get("sender") == "ai" else "user"
        
        if history_to_process and history_to_process[-1]["role"] == role:
            history_to_process[-1]["content"] += f"\n\n{txt}"
        else:
            history_to_process.append({"role": role, "content": txt})

    # 3. Handle the current message (merge if last history was user)
    current_msg_text = message.strip()
    if history_to_process and history_to_process[-1]["role"] == "user":
        history_to_process[-1]["content"] += f"\n\n{current_msg_text}"
    else:
        history_to_process.append({"role": "user", "content": current_msg_text})

    # 4. vLLM STRICT RULES: Must start with USER after SYSTEM, and must alternate.
    valid_alternating_messages = []
    for msg in history_to_process:
        if not valid_alternating_messages:
            if msg["role"] == "assistant":
                continue # Skip assistant if it tries to start the conversation
            valid_alternating_messages.append(msg)
        else:
            if msg["role"] != valid_alternating_messages[-1]["role"]:
                valid_alternating_messages.append(msg)
            else:
                valid_alternating_messages[-1]["content"] += f"\n\n{msg['content']}"

    final_messages.extend(valid_alternating_messages)

    payload = {
        "model": settings.VLLM_MODEL,
        "messages": final_messages,
        "temperature": 0.2,
        "max_tokens": 1024
    }

    logger.debug(f"Starting SSE stream: messages={len(final_messages)}")
    try:
        async for chunk in vllm_service.stream_vllm_api(payload):
            data = {"content": chunk}
            yield f"data: {json.dumps(data)}\n\n"
        logger.debug("SSE stream complete")
    except Exception as e:
        logger.error(f"SSE stream error: {e}")
        error_data = {"content": f"⚠️ **AI Stream Error**: {str(e)}. Please refresh or try again."}
        yield f"data: {json.dumps(error_data)}\n\n"
