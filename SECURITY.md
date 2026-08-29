# Security policy

## Model

Reweave executes *content-derived* logic (CSS selectors synthesized from
untrusted web pages), so the design treats the web and LLM output as hostile:

- Synthesized selectors are **data**, executed only by `soupsieve`'s CSS
  engine — never `eval`, never templated into code.
- No candidate reaches production without golden-record validation **and** a
  named human approval; the audit ledger records both.
- The MCP surface annotates deploy/discard tools as destructive so harnesses
  interpose their own approval UI (defense in depth).
- Fetch credentials (`BRIGHTDATA_API_KEY`) live in environment variables and
  are never persisted to the registry or logs.

## Reporting a vulnerability

Please **do not** open a public issue for security reports. Email
`vnarasingamoorthy@gmail.com` with details and reproduction steps; you'll get
an acknowledgment within 72 hours. Coordinated disclosure appreciated.
