"""Structured JSON logging and execution trace context."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, IO, Mapping, Optional

_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "satquery_trace_id", default=None
)


class JsonLogFormatter(logging.Formatter):
    """Serialize standard logging events and SatQuery fields as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = _trace_id.get()
        if trace_id is not None:
            payload["trace_id"] = trace_id
        structured = getattr(record, "satquery_fields", None)
        if isinstance(structured, Mapping):
            payload.update(structured)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str, separators=(",", ":"))


def configure_logging(
    level: str = "INFO",
    *,
    stream: Optional[IO[str]] = None,
) -> None:
    """Configure SatQuery's logger without changing application root handlers."""
    level_name = level.upper()
    if level_name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"Unknown logging level {level!r}")
    resolved_level = getattr(logging, level_name)
    logger = logging.getLogger("satquery")
    logger.setLevel(resolved_level)
    logger.propagate = False
    handler = next(
        (item for item in logger.handlers if getattr(item, "_satquery_json", False)),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler._satquery_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    handler.setFormatter(JsonLogFormatter())


def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger_name: str = "satquery.execution",
    **fields: Any,
) -> None:
    logging.getLogger(logger_name).log(
        level,
        event,
        extra={"satquery_fields": {"event": event, **fields}},
    )


def redact_sensitive(value: Any) -> Any:
    """Redact common secret-bearing keys before writing structured parameters."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(
                marker in normalized
                for marker in (
                    "token",
                    "secret",
                    "password",
                    "credential",
                    "api_key",
                    "authorization",
                    "access_key",
                    "private_key",
                )
            ):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    return value


class trace_context:
    """Context manager binding one trace identifier to this async context."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._token: Optional[contextvars.Token[Optional[str]]] = None

    def __enter__(self) -> "trace_context":
        self._token = _trace_id.set(self.trace_id)
        return self

    def __exit__(self, *_args: Any) -> None:
        if self._token is not None:
            _trace_id.reset(self._token)
