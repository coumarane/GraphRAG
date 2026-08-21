"""Secret and sensitive-value redaction for logs and error payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_REDACTED = "[REDACTED]"
_TRUNCATED = "[REDACTED:truncated]"

# Authorization headers, bearer/api keys, common secret env-style values.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)^(authorization|api[_-]?key|access[_-]?key|secret|password|token|"
    r"x-api-key|client_secret|refresh_token|private_key|session|cookie)$"
)

# Inline secret material in free-form strings.
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b("
    r"bearer\s+[a-z0-9\-._~+/]+=*"
    r"|sk-[a-z0-9]{16,}"
    r"|api[_-]?key\s*[:=]\s*\S+"
    r"|password\s*[:=]\s*\S+"
    r"|token\s*[:=]\s*\S+"
    r")\b"
)

# Query params commonly used for pre-signed / credentialed URLs.
_PRESIGN_QUERY_KEYS = frozenset(
    {
        "x-amz-signature",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-algorithm",
        "x-amz-date",
        "x-amz-expires",
        "x-amz-signedheaders",
        "signature",
        "sig",
        "awsaccesskeyid",
        "token",
        "access_token",
        "id_token",
    }
)

_DEFAULT_MAX_STRING = 2_048
_SENSITIVE_CONTENT_KEYS = frozenset(
    {
        "content",
        "text",
        "body",
        "document_content",
        "raw_content",
        "normalized_content",
        "prompt",
        "messages",
    }
)


def redact_string(value: str, *, max_length: int = _DEFAULT_MAX_STRING) -> str:
    """Redact inline secrets and truncate oversized strings."""
    if not value:
        return value
    redacted = _INLINE_SECRET_RE.sub(_REDACTED, value)
    if _looks_like_presigned_url(redacted):
        redacted = redact_url(redacted)
    if len(redacted) > max_length:
        return f"{redacted[:max_length]}...{_TRUNCATED}"
    return redacted


def redact_url(url: str) -> str:
    """Strip userinfo and sensitive query parameters from a URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return _REDACTED
    query = parts.query
    if query:
        kept: list[str] = []
        for pair in query.split("&"):
            if not pair:
                continue
            key = pair.split("=", 1)[0].lower()
            if key in _PRESIGN_QUERY_KEYS or "sign" in key or "token" in key:
                kept.append(f"{pair.split('=', 1)[0]}={_REDACTED}")
            else:
                kept.append(pair)
        query = "&".join(kept)
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, query, ""))


def redact_mapping(
    data: Mapping[str, Any],
    *,
    max_string: int = _DEFAULT_MAX_STRING,
) -> dict[str, Any]:
    """Recursively redact sensitive keys and string values."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        key_str = str(key)
        if _SENSITIVE_KEY_RE.match(key_str):
            result[key_str] = _REDACTED
            continue
        if key_str.lower() in _SENSITIVE_CONTENT_KEYS and isinstance(value, str):
            result[key_str] = redact_string(value, max_length=min(256, max_string))
            continue
        result[key_str] = redact_value(value, max_string=max_string)
    return result


def redact_value(value: Any, *, max_string: int = _DEFAULT_MAX_STRING) -> Any:
    """Redact an arbitrary JSON-ish value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_string(value, max_length=max_string)
    if isinstance(value, Mapping):
        return redact_mapping(value, max_string=max_string)
    if isinstance(value, (list, tuple)):
        return [redact_value(item, max_string=max_string) for item in value]
    return str(value)


def structlog_redaction_processor(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Structlog processor that redacts sensitive event fields in place."""
    for key in list(event_dict.keys()):
        if _SENSITIVE_KEY_RE.match(str(key)):
            event_dict[key] = _REDACTED
            continue
        event_dict[key] = redact_value(event_dict[key])
    return event_dict


def _looks_like_presigned_url(value: str) -> bool:
    lowered = value.lower()
    if not lowered.startswith(("http://", "https://")):
        return False
    return any(token in lowered for token in ("x-amz-", "signature=", "access_token="))


__all__ = [
    "redact_mapping",
    "redact_string",
    "redact_url",
    "redact_value",
    "structlog_redaction_processor",
]
