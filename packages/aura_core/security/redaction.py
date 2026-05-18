# -*- coding: utf-8 -*-
"""Centralized redaction for diagnostics, exports and debug reports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REDACTED = "***REDACTED***"

SECRET_TOKENS = (
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "cookie",
    "authorization",
    "private_key",
    "credential",
    "bearer",
    "session",
    "access_key",
    "refresh_token",
)

_SECRET_KEY_PATTERN = "|".join(re.escape(token).replace("_", r"[_-]?") for token in SECRET_TOKENS)
_JSON_DOUBLE_QUOTED_SECRET_RE = re.compile(
    rf'(?i)("(?P<key>[^"]*(?:{_SECRET_KEY_PATTERN})[^"]*)"\s*:\s*)"(?P<value>(?:\\.|[^"\\])*)"',
)
_JSON_SINGLE_QUOTED_SECRET_RE = re.compile(
    rf"(?i)('(?P<key>[^']*(?:{_SECRET_KEY_PATTERN})[^']*)'\s*:\s*)'(?P<value>(?:\\.|[^'\\])*)'",
)
_KEY_VALUE_SECRET_RE = re.compile(
    rf"(?im)\b(?P<key>[A-Za-z0-9_.-]*(?:{_SECRET_KEY_PATTERN})[A-Za-z0-9_.-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^\s,;'\"]+)"
    r"(?P=quote)"
)
_AUTH_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)")
_BARE_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{8,})")


def redact_json(value: Any) -> Any:
    """Return a JSON-compatible structure with sensitive fields scrubbed."""

    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_secret_key(key):
                result[key] = REDACTED
            else:
                result[key] = redact_json(item)
        return result
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, tuple):
        return [redact_json(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    """Scrub common secret patterns in free-form logs and text files."""

    raw = str(text)
    raw = _JSON_DOUBLE_QUOTED_SECRET_RE.sub(lambda m: f'{m.group(1)}"{REDACTED}"', raw)
    raw = _JSON_SINGLE_QUOTED_SECRET_RE.sub(lambda m: f"{m.group(1)}'{REDACTED}'", raw)
    raw = _AUTH_BEARER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", raw)
    raw = _BARE_BEARER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", raw)
    raw = _KEY_VALUE_SECRET_RE.sub(lambda m: f"{m.group('key')}{m.group('sep')}{m.group('quote')}{REDACTED}{m.group('quote')}", raw)
    return raw


def redact_file_payload(path: str | Path, payload: bytes | str | None = None) -> str:
    """Read or scrub a text payload using JSON/JSONL-aware redaction."""

    file_path = Path(path)
    if payload is None:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    elif isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload)

    suffix = file_path.suffix.lower()
    if suffix == ".json":
        try:
            return json.dumps(redact_json(json.loads(text)), ensure_ascii=False, indent=2, default=str)
        except Exception:
            return redact_text(text)
    if suffix == ".jsonl":
        lines: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                lines.append(json.dumps(redact_json(json.loads(line)), ensure_ascii=False, default=str))
            except Exception:
                lines.append(redact_text(line))
        return "\n".join(lines) + ("\n" if lines else "")
    return redact_text(text)


def _is_secret_key(key: object) -> bool:
    normalized = str(key or "").lower().replace("-", "_").replace(".", "_")
    return any(token in normalized for token in SECRET_TOKENS)
