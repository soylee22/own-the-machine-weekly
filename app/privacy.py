"""Public-output and feed sanitisation checks."""

from __future__ import annotations

import html
import ipaddress
import re
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PRIVATE_KEY_PARTS = (
    "unit",
    "share",
    "balance",
    "cost",
    "purchase",
    "selling",
    "portfolio_value",
    "account",
    "credential",
    "token",
    "secret",
    "password",
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
# Require a telephone prefix and separators. This deliberately does not match
# ISO dates, prices, identifiers or plain digit strings.
_PHONE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[ -](?:\(?\d{2,4}\)?[ -])\d{3,4}[ -]\d{3,4}|\(?0\d{2,4}\)?[ -]\d{3,4}[ -]\d{3,4})(?!\w)"
)
_TAGS = re.compile(r"<[^>]+>")


def sanitise_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", text)
    text = _TAGS.sub(" ", text)
    text = _EMAIL.sub("[email removed]", text)
    text = _PHONE.sub("[phone removed]", text)
    return " ".join(text.split()).strip()


def sanitise_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Only public HTTP URLs are allowed: {value!r}")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL user information is not allowed")
    hostname = (parts.hostname or "").lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal", ".lan")):
        raise ValueError("Non-public host is not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast):
        raise ValueError("Non-public host is not allowed")
    safe_query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if any(part in lowered for part in ("key", "token", "secret", "password", "email", "account")):
            continue
        if len(item) > 500:
            continue
        safe_query.append((key, item))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


def _key_is_private(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in PRIVATE_KEY_PARTS)


def find_privacy_violations(value: object, path: str = "$", violations: list[str] | None = None) -> list[str]:
    violations = violations if violations is not None else []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = f"{path}.{key}"
            if _key_is_private(str(key)):
                violations.append(f"private field at {key_path}")
            find_privacy_violations(item, key_path, violations)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            find_privacy_violations(item, f"{path}[{index}]", violations)
    elif isinstance(value, str):
        if _EMAIL.search(value):
            violations.append(f"email at {path}")
        leaf = path.rsplit(".", 1)[-1].lower()
        if leaf in {"phone", "telephone", "mobile", "contact"} and _PHONE.search(value):
            violations.append(f"phone at {path}")
    return violations


def assert_public_payload(value: object) -> None:
    violations = find_privacy_violations(value)
    if violations:
        raise ValueError("Public payload failed privacy check: " + "; ".join(violations[:8]))
