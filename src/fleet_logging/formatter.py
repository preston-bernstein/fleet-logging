"""The canonical JSON log line for this library's structured-logging
contract.

Two usage shapes, because the hand-rolled implementations this package
replaces used two different ones and this package is meant to be a strict
superset of both:

1. **stdlib `logging`-based**: `configure_logging(service)` once at the
   application's entry point, then ordinary
   `logging.getLogger(__name__).info(...)` everywhere else, with extra
   fields passed via `extra={...}`.
2. **Direct function call**, for a package with no long-lived process to
   configure — every invocation is a single oneshot CLI command, so
   `log_event(...)` printing straight to a stream *is* the entry point's
   own output configuration:
   `log_event("info", "batch.completed", run_id=run_id, outcome="ok")`.

Both paths converge on the same JSON shape and the same redaction (see
`fleet_logging.redact`). `level` is always emitted in the caller's own
native spelling — a downstream log-processing pipeline is the place to
canonicalize it, if that's wanted; this package must never pre-canonicalize.

**Library-vs-application rule:** only an application's own entry point
calls `configure_logging()`. Every importable module should use
`logging.getLogger(__name__)` (or `log_event` directly) and never touch a
handler, formatter, or `basicConfig` itself.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from typing import TextIO

from fleet_logging.redact import redact_fields

SCHEMA_VERSION = 1

# Every attribute a stock LogRecord carries — used to tell "a field the
# caller passed via extra=" apart from stdlib bookkeeping. Computed from a
# real LogRecord instead of hand-copied so a future Python version's added
# attributes (e.g. `taskName` in 3.12) are picked up automatically rather
# than leaking into every line as a spurious field.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Renders one `logging.LogRecord` as one canonical JSON line.

    Any field a caller passes via `extra={...}` (run_id, outcome,
    items_processed, ...) is included verbatim, except the redaction
    deny-list, which is scrubbed here as defense-in-depth on top of whatever
    a downstream log-processing pipeline does — this is the second layer,
    not the only one.
    """

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        line: dict = {
            "schema_version": SCHEMA_VERSION,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,  # native Python spelling; pipeline canonicalizes
            "service": self.service,
            "event": getattr(record, "event", record.name),
            "msg": record.getMessage(),
        }
        extra = {
            key: val
            for key, val in record.__dict__.items()
            if key not in _STANDARD_ATTRS and key != "event" and val is not None
        }
        line.update(redact_fields(extra))
        if record.exc_info and "err_type" not in line:
            exc_type = record.exc_info[0]
            line["err_type"] = exc_type.__name__ if exc_type else "Exception"
        return json.dumps(line, default=str)


class _StreamHandler(logging.StreamHandler):
    """A StreamHandler that resolves its target stream at EMIT time rather
    than binding to whatever object it was when the handler was constructed.

    Needed because `configure_logging()` is deliberately idempotent (a real,
    re-entrant call from application code must never install a second
    handler), but a test runner's `CliRunner`-style stdout/stderr swapping
    per invocation would otherwise leave a handler frozen to the first
    stream it ever saw. In production the stream never changes after
    process startup, so this has no observable effect there.
    """

    def __init__(self, stream: TextIO) -> None:
        super().__init__(stream=stream)
        self._get_stream = lambda: stream

    @property
    def stream(self):
        return self._get_stream()

    @stream.setter
    def stream(self, value) -> None:  # pragma: no cover - base class assigns once
        pass


def configure_logging(
    service: str, level: int = logging.INFO, stream: TextIO | None = None
) -> None:
    """Application entry-point only (see module docstring). Configures the
    root logger with a single stream handler using `JsonFormatter`.

    `stream` defaults to `sys.stdout` — the canonical line goes to stdout,
    one line per event. Pass `sys.stderr` for a deliberate stdout/stderr
    split (machine-readable JSON on stderr, human-facing CLI output on
    stdout).

    Idempotent: a second call (re-entrant CLI invocation, a test importing
    twice) is a no-op rather than installing a duplicate handler. Checks for
    OUR OWN handler type specifically, not `root.handlers` truthiness — a
    test runner may already have attached unrelated handlers to the root
    logger before this ever runs, and a bare `if root.handlers: return`
    would treat those as "already configured" and silently never install
    this one at all.
    """
    target = stream if stream is not None else sys.stdout
    root = logging.getLogger()
    if any(isinstance(h, _StreamHandler) for h in root.handlers):
        return
    handler = _StreamHandler(target)
    handler.setFormatter(JsonFormatter(service))
    root.addHandler(handler)
    root.setLevel(level)
    # Keep noisy third-party debug HTTP logs (which routinely embed
    # Authorization headers / API keys in their own log lines) below what
    # actually reaches a handler.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def new_run_id(prefix: str = "run") -> str:
    """A correlation id for one unit of work — one cron fire, one pipeline
    run, one CLI invocation.

    Superset of both source implementations this replaces: reuses `$RUN_ID`
    if a parent process already minted one (lets a shell script and the
    Python subprocess it launches share one id end to end), else mints a
    fresh time-prefixed, randomly-suffixed id (the random suffix avoids two
    invocations in the same second colliding, which a PID-suffixed
    alternative would not fully guard against under a process-pool launcher
    reusing PIDs).
    """
    return (
        os.environ.get("RUN_ID")
        or f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    )


def log_event(
    level: str,
    event: str,
    msg: str | None = None,
    *,
    service: str,
    stream: TextIO | None = None,
    **fields,
) -> None:
    """Emit one canonical JSON log line directly, with no `logging` module
    configuration required — for a package with no long-lived process to
    configure.

    `level` — the caller's own native spelling (`debug`/`info`/`warn`/
    `error`/`critical`); a downstream log-processing pipeline is the place
    to map it to a canonical enum, never this function.
    `event` — a short, stable, dot-namespaced string (`collect.completed`,
    `run.failed`) — the thing a dashboard panel or an `absent()`-style alert
    actually filters on; `msg` is prose for a human reading the log and
    must never be what anything alerts on.
    `stream` defaults to `sys.stdout` per the canonical line; pass
    `sys.stderr` for a deliberate stdout/stderr split.
    `fields` — everything else (`run_id`, `outcome`, work-quantity,
    `err_type`/`err_msg`, `duration_ms`, ...) per the canonical shape.
    """
    target = stream if stream is not None else sys.stdout
    line = {
        "schema_version": SCHEMA_VERSION,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level,
        "service": service,
        "event": event,
        "msg": msg if msg is not None else event,
        **redact_fields(fields),
    }
    print(json.dumps(line, default=str), file=target, flush=True)
