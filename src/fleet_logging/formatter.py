"""The canonical JSON log line — internal-infra CONVENTIONS.md §18 (fleet
logging contract).

Two usage shapes, because the two existing hand-rolled implementations this
package replaces used two different ones and this package is meant to be a
strict superset of both:

1. **stdlib `logging`-based** (internal-corpus-service's `logging_setup.py` shape):
   `configure_logging(service)` once at the application's entry point, then
   ordinary `logging.getLogger(__name__).info(...)` everywhere else, with
   extra fields passed via `extra={...}`.
2. **Direct function call** (internal-monitor-service's `log.py` shape), for a
   package with no long-lived process to configure — every invocation is a
   single oneshot CLI command, so `log_event(...)` printing straight to a
   stream *is* the entry point's own output configuration:
   `log_event("info", "batch.completed", run_id=run_id, outcome="ok")`.

Both paths converge on the same JSON shape and the same redaction (see
`fleet_logging.redact`). `level` is always emitted in the caller's own
native spelling — per §18 the shared Loki pipeline canonicalizes it; this
package must never pre-canonicalize.

**Library-vs-application rule (§18):** only an application's own entry
point calls `configure_logging()`. Every importable module should use
`logging.getLogger(__name__)` (or `log_event` directly) and never touch a
handler, formatter, or `basicConfig` itself — see the grep in §18 that
catches a violation.
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
# than leaking into every line as a spurious field. (Ported verbatim from
# internal-corpus-service's logging_setup.py — same reasoning applies here.)
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Renders one `logging.LogRecord` as one canonical §18 JSON line.

    Any field a caller passes via `extra={...}` (run_id, outcome,
    items_processed, ...) is included verbatim, except the §18 redaction
    deny-list, which is scrubbed here as defense-in-depth (the shared Loki
    `stage.replace` is the enforced backstop; this is the second layer,
    matching internal-monitor-service's `_scrub()` — internal-corpus-service's original did
    not redact at all, so this is a strict superset of both source
    implementations, not a like-for-like port).
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
    process startup, so this has no observable effect there. (Ported
    verbatim from internal-corpus-service's `_StdoutHandler`, generalized to either
    stream.)
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

    `stream` defaults to `sys.stdout` — §18's canonical line goes "to
    stdout, one line per event". Pass `sys.stderr` to match
    internal-monitor-service's deliberate stdout/stderr split (machine-readable
    JSON on stderr, human-facing CLI output on stdout).

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
    """A correlation id for one unit of work (§18 Correlation) — one cron
    fire, one campaign run, one CLI invocation.

    Superset of both source implementations: reuses `$RUN_ID` if a parent
    process already minted one (internal-corpus-service's behavior — lets a shell script
    and the Python subprocess it launches share one id end to end), else
    mints a fresh time-prefixed, randomly-suffixed id (internal-monitor-service's
    behavior — the random suffix avoids two invocations in the same second
    colliding, which internal-corpus-service's PID-suffixed version did not fully
    guard against under a process-pool launcher reusing PIDs).
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
    """Emit one canonical §18 JSON log line directly, with no `logging`
    module configuration required — internal-monitor-service's shape, for a
    package with no long-lived process to configure.

    `level` — the caller's own native spelling (`debug`/`info`/`warn`/
    `error`/`critical`); the shared pipeline maps it to the fleet's
    canonical enum, never this function.
    `event` — a short, stable, dot-namespaced string (`collect.completed`,
    `run.failed`) — the thing a dashboard panel or `absent()` alert
    actually filters on; `msg` is prose for a human in Grafana Explore and
    must never be what anything alerts on.
    `stream` defaults to `sys.stdout` per §18's canonical line; pass
    `sys.stderr` to match internal-monitor-service's convention.
    `fields` — everything else (`run_id`, `outcome`, work-quantity,
    `err_type`/`err_msg`, `duration_ms`, ...) per §18's canonical shape.
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
