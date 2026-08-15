"""Defense-in-depth redaction — home-infra CONVENTIONS.md §18 "Redaction".

The shared Loki `loki.process` pipeline's `stage.replace` is the enforced
backstop for these field names fleet-wide; this module exists so a field
never even reaches stdout/stderr in the first place, matching
algo-macro-monitor's `_scrub()` (which algo-corpus's `logging_setup.py` did
not do — this module is a strict superset covering both call sites' needs).

Residual gap, stated rather than hidden (per §18): a secret value logged
under an unlisted or misspelled key name still reaches Loki. This closes the
common case, not every case.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

# The fleet-wide deny-list, verbatim from CONVENTIONS.md §18.
REDACT_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "api_key",
        "apikey",
        "secret",
        "authorization",
        "access_token",
        "refresh_token",
        "ssn",
        "cookie",
        "session",
    }
)

_REDACTED = "[REDACTED]"


def _strip_query_string(value: str) -> str:
    """§18: "never log a URL query string" — query strings carry API keys and
    session tokens far more often than path segments do. Best-effort: only
    touches values that actually parse as a URL with a scheme and a query
    string; anything else (a bare word, a non-URL string) passes through
    unchanged.
    """
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.query:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def redact_fields(fields: dict) -> dict:
    """Return a copy of `fields` with deny-listed keys replaced by
    `[REDACTED]` (case-insensitive key match) and any URL-shaped string
    value stripped of its query string.
    """
    out: dict = {}
    for key, value in fields.items():
        if key.lower() in REDACT_KEYS:
            out[key] = _REDACTED
        elif isinstance(value, str):
            out[key] = _strip_query_string(value)
        else:
            out[key] = value
    return out
