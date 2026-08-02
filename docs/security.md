# Security

- Tenant context is mandatory on store protocols.
- Secrets never appear in logs (structlog redaction processor).
- Uploads are MIME-sniffed, size-capped, page-capped and ZIP-guarded.
- URL fetch blocks SSRF targets and credentialed URLs.
- Prompt trust boundaries wrap document/evidence content.
- Optional malware scanner hook runs before intake persistence.
- Cypher and SQL paths use parameterization / allowlists.
