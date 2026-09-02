ANALYZE_CONFIG_PROMPT = """You are a cybersecurity expert specializing in network and firewall configurations.
Analyze the following configuration files against the {framework} framework.
Identify any security misconfigurations, overly permissive rules, or compliance violations.

First, identify the vendor, operating system, and version for each configuration file provided.

Return the results as a single JSON object with two keys: "file_metadata" and "issues".

"file_metadata" should be an array of objects, one for each file:
{{
  "file": "filename.txt",
  "vendor": "Cisco",
  "os": "IOS",
  "version": "15.4(3)M1"
}}

"issues" should be an array of objects. Each object in the "issues" array MUST match this exact structure:
{{
  "id": "vuln-001",
  "severity": "High", 
  "title": "Permissive Any-Any Rule Detected",
  "description": "A firewall rule was found that allows any traffic from any source to any destination.",
  "file": "filename.txt",
  "line": 10,
  "originalCode": "rule 10 allow any any",
  "proposedCode": "rule 10 allow 10.0.0.0/8 192.168.1.0/24",
  "strategy": "Restrict the rule to only allow necessary traffic."
}}

Severity must be one of: "High", "Medium", "Low".

Output strictly the JSON object. Do not wrap it in markdown block quotes (```json).
"""

CHUNK_CONTEXT_NOTE = """
NOTE: The configuration below is part {part} of {total} of the file "{filename}".
It was split at section boundaries because the full file is too large to analyze at once.
Only report issues visible in this part; other parts are analyzed separately.
Use "{filename}" as the "file" value, and report "line" numbers relative to the text
provided below (the first line below is line 1).
"""

EXTRACT_CONFIG_PROMPT = """You are a network parsing assistant.
Your ONLY job is to extract all security-relevant configurations from the provided raw text chunk.
This includes:
- Access Control Lists (ACLs) and Firewall Rules
- NAT Rules
- Network Object and Object Group definitions
- Port/Service Object definitions
- Security Zones and Interface assignments

Do NOT extract noise such as SSL certificates, routing tables, interface statistics, or raw logs.
Output the extracted text exactly as it appears in the source, keeping the original syntax.
Do NOT provide explanations or commentary. If no relevant config is found, return nothing.
"""
