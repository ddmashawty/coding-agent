"""Strip secrets from anything that might be written to disk or printed."""

from __future__ import annotations


def redact_secrets(text: str, api_key: str = "") -> str:
    """Replace only the exact key value. Leave other reasoning text alone."""
    if not text or not api_key:
        return text
    return text.replace(api_key, "[REDACTED]")


def redact_obj(value: object, api_key: str = "") -> object:
    if isinstance(value, str):
        return redact_secrets(value, api_key)
    if isinstance(value, list):
        return [redact_obj(item, api_key) for item in value]
    if isinstance(value, dict):
        return {key: redact_obj(item, api_key) for key, item in value.items()}
    return value
