"""Secret redaction helpers.

Audit logs, configuration-change records and error messages must never carry a
credential in clear text. Every helper in this module is deliberately
conservative: a value is redacted when its *name* looks sensitive, and the
redacted placeholder never reveals any part of the original value.

This module contains no configuration of its own so it can be imported from
any layer without creating a circular dependency.
"""

import re
from typing import Any

# Placeholder written in place of a secret value. It carries no information
# about the length or content of the original value.
REDACTED_PLACEHOLDER: str = "***REDACTED***"

# Parameter-name fragments that mark a value as sensitive. Matching is done on
# a lower-cased, non-alphanumeric-normalised form of the name so that
# "password", "PASSWORD", "db_password" and "db-password" all match.
_SENSITIVE_NAME_FRAGMENTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "apikey",
    "api_key",
    "private_key",
    "privatekey",
    "passphrase",
    "authorization",
    "auth_key",
    "salt",
    "signature",
)

# A connection URL may embed the password in its userinfo section, so the URL
# itself is treated as sensitive when it carries credentials.
_URL_CREDENTIAL_PATTERN = re.compile(r"://[^/@\s]*:[^/@\s]*@")


def _normalize(name: str) -> str:
    """Normalise a parameter name for fragment matching."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower())


def is_sensitive_name(name: str) -> bool:
    """Return True when a parameter name identifies a secret value.

    Args:
        name: The parameter or dictionary key to inspect.

    Returns:
        True when the name matches a known sensitive fragment.
    """
    normalized = _normalize(name)
    return any(fragment in normalized for fragment in _SENSITIVE_NAME_FRAGMENTS)


def redact_value(value: Any) -> Any:
    """Return a redacted representation of a single sensitive value.

    Non-string values are replaced by the placeholder as well: a numeric
    secret is still a secret, and its type alone leaks information.
    """
    if value is None:
        return None
    return REDACTED_PLACEHOLDER


def redact_text(value: str) -> str:
    """Redact credentials embedded in a free-form string.

    Connection URLs with an embedded password are rewritten so that only the
    placeholder remains in the userinfo section.
    """
    return _URL_CREDENTIAL_PATTERN.sub(f"://{REDACTED_PLACEHOLDER}@", value)


def redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a mapping with every sensitive entry redacted.

    Nested mappings and sequences are redacted recursively so a secret cannot
    hide inside a sub-structure.
    """
    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        if is_sensitive_name(key):
            redacted[key] = redact_value(value)
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list | tuple):
            redacted[key] = [redact_mapping_item(item) for item in value]
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value
    return redacted


def redact_mapping_item(item: Any) -> Any:
    """Redact a single item that may itself be a mapping, sequence or scalar."""
    if isinstance(item, dict):
        return redact_mapping(item)
    if isinstance(item, list | tuple):
        return [redact_mapping_item(sub_item) for sub_item in item]
    if isinstance(item, str):
        return redact_text(item)
    return item


def redact_details(details: Any) -> Any:
    """Redact an arbitrary audit-detail payload.

    Mappings and sequences are walked recursively; a plain string is scanned
    for embedded credentials; every other type is returned unchanged because
    it carries no credential material.
    """
    if isinstance(details, dict):
        return redact_mapping(details)
    if isinstance(details, list | tuple):
        return [redact_mapping_item(item) for item in details]
    if isinstance(details, str):
        return redact_text(details)
    return details
