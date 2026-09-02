TRANSLATE_CONFIG_PROMPT = """Role: You are a Principal Network Architect specializing in {target_vendor}.

Task: First identify the vendor and OS of the attached source configuration, then translate it into valid, commit-ready {target_vendor} configuration commands.
{vendor_specific_rules}
General Rules:
- Preserve the security intent of every rule, object, and interface assignment. Do not invent policies that are not in the source.
- If a source construct has no equivalent on {target_vendor}, emit a comment (in the target's comment syntax) explaining what was skipped and why.
- NEVER echo plaintext passwords, pre-shared keys, or SNMP community strings from the source. Replace them with [REDACTED].

Output Format: Provide only the {target_vendor} CLI commands, grouped by category (Interfaces, Objects/Address Books, NAT, Policies). No prose outside of configuration comments.

Source Configuration:
{source_config}"""


# Vendor-specific syntax guidance injected into {vendor_specific_rules}.
# Keys are matched case-insensitively as substrings of the requested target_vendor
# (the frontend sends e.g. "Juniper Junos", "Palo Alto PAN-OS").
VENDOR_RULES = {
    "juniper": """
Strict Syntax Rules for Junos (SRX Series) — output "set" commands only:

Interfaces: Always use logical units (e.g., ge-0/0/0.0). Do not use nameif or security-level. Use description for interface names.

Security Zones: Map source interface names/zones to Junos security-zones. Ensure interfaces are assigned to zones using the .0 unit suffix.

Address Books: Use the set security address-book global hierarchy for all network objects and object-groups.

Applications:
- NEVER use destination-port or protocol within a security policy match statement.
- Use built-in applications (e.g., junos-https, junos-smtp, junos-icmp-all).
- If a custom port is required, define it first using set applications application [NAME] protocol [TCP/UDP] destination-port [PORT].

Policy Structure:
- Group policies by zone-pairs (e.g., from-zone inside to-zone outside).
- Place specific host-to-host policies above general subnet policies.
- Include a DEFAULT_LOG_DENY policy at the end of each zone-pair with then deny and then log.

NAT: Translate dynamic PAT to security nat source. Use source-nat interface logic.

Inspection: Ignore source inspection constructs (e.g., Cisco policy-map or inspect commands). Do not attempt to translate them into UTM/IDP unless specifically requested.

Host Inbound: For the management interface, include set security zones security-zone [ZONE] host-inbound-traffic system-services [ssh/ping/https].
""",
}


def get_vendor_rules(target_vendor: str) -> str:
    """Return vendor-specific rule text for the requested target vendor, or '' if none."""
    needle = target_vendor.lower()
    for key, rules in VENDOR_RULES.items():
        if key in needle:
            return rules
    return ""
