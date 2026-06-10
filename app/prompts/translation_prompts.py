TRANSLATE_CONFIG_PROMPT = """Role: You are a Principal Network Architect specializing in Juniper Junos (SRX Series).

Task: Translate the attached Cisco ASA configuration into valid, commit-ready Juniper Junos "set" commands.

Strict Syntax Rules for Junos:

Interfaces: Always use logical units (e.g., ge-0/0/0.0). Do not use nameif or security-level. Use description for interface names.

Security Zones: Map the ASA nameif to Junos security-zones. Ensure interfaces are assigned to zones using the .0 unit suffix.

Address Books: Use the set security address-book global hierarchy for all network objects and object-groups.

Applications:
- NEVER use destination-port or protocol within a security policy match statement.
- Use built-in applications (e.g., junos-https, junos-smtp, junos-icmp-all).
- If a custom port is required, define it first using set applications application [NAME] protocol [TCP/UDP] destination-port [PORT].

Policy Structure:
- Group policies by zone-pairs (e.g., from-zone inside to-zone outside).
- Place specific host-to-host policies above general subnet policies.
- Include a DEFAULT_LOG_DENY policy at the end of each zone-pair with then deny and then log.

NAT: Translate ASA NAT (Dynamic PAT) to security nat source. Use source-nat interface logic.

Inspection: Ignore Cisco policy-map or inspect commands. Do not attempt to translate them into UTM/IDP unless specifically requested.

Host Inbound: For the management interface, include set security zones security-zone [ZONE] host-inbound-traffic system-services [ssh/ping/https].

Output Format: Provide only the CLI "set" commands. Group them by category (Interfaces, Address Books, Applications, NAT, Policies).

Source Configuration:
{source_config}"""