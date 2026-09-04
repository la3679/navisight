"""Structured logging and request correlation.

Deliberately small. SOUL.md §5 asks for structured telemetry without building
an observability stack that nothing needs yet; OpenTelemetry is documented as a
future step in ``docs/operations/`` rather than installed speculatively.

Two rules are enforced here rather than left to discipline:

* **No secrets in logs.** :func:`redact` scrubs known-sensitive keys.
* **No log injection.** User-supplied strings have newlines and control
  characters stripped before they reach a log line, so a crafted vessel name
  cannot forge a second log record (SOUL.md §10).
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Correlates a frontend request with its API handling and any agent run it
#: triggers. Surfaced to clients in the `X-Request-ID` response header.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_KEYS = frozenset(
    {
        "openai_api_key",
        "llm_api_key",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "token",
        "secret",
        "mongodb_uri",
        "cookie",
        "set-cookie",
    }
)

_LOG_RECORD_BUILTINS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def new_request_id() -> str:
    """A short, unique request identifier."""
    return uuid.uuid4().hex[:16]


def scrub(value: str, *, max_length: int = 200) -> str:
    """Make an untrusted string safe to put in a log line.

    Strips newlines and control characters so a crafted value cannot inject a
    forged log record, and truncates so one field cannot flood the log.
    """
    cleaned = "".join(character for character in value if character.isprintable())
    return cleaned[:max_length]


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace values of known-sensitive keys with a placeholder."""
    return {
        key: ("***" if key.lower() in _SENSITIVE_KEYS else value) for key, value in payload.items()
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": "navisight-api",
            "request_id": request_id_var.get(),
            "message": record.getMessage(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _LOG_RECORD_BUILTINS and not key.startswith("_")
            }
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable output for local development."""

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _LOG_RECORD_BUILTINS and not key.startswith("_")
        }
        suffix = ""
        if extras:
            redacted = redact(extras)
            suffix = "  " + " ".join(f"{key}={value}" for key, value in redacted.items())
        request_id = request_id_var.get()
        prefix = f"[{request_id}] " if request_id != "-" else ""
        line = f"{record.levelname:<7} {prefix}{record.name}: {record.getMessage()}{suffix}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(*, level: str = "INFO", log_format: str = "console") -> None:
    """Install the root logging configuration. Idempotent."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if log_format == "json" else ConsoleFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # The access log duplicates our own request logging, with less detail.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("pymongo").setLevel(logging.WARNING)
