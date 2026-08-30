# fleet-logging

fleet-logging is a shared Python library for a personal home lab's fleet of
internal services. It implements one canonical JSON structured-logging
format so each service imports a single implementation instead of
hand-writing its own JSON formatter and drifting out of sync — which is
exactly what happened before this package existed: several internal
Python services independently reimplemented the same logging shape.

[![CI](https://github.com/preston-bernstein/fleet-logging/actions/workflows/ci.yml/badge.svg)](https://github.com/preston-bernstein/fleet-logging/actions/workflows/ci.yml)  [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab)](pyproject.toml)  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Library, not a service

fleet-logging is a library, not a running service — a consumer *imports* it
directly.

## The JSON log line contract

Every log line this library emits is a single-line JSON object with these
fields:

| Field | Meaning |
|---|---|
| `schema_version` | Integer, currently `1`. Bump when the shape changes. |
| `ts` | UTC timestamp, `%Y-%m-%dT%H:%M:%SZ`. |
| `level` | The caller's own native spelling — `debug`/`info`/`warn`/`error`/`critical` for `log_event()`, or Python's `DEBUG`/`INFO`/... for stdlib `logging`. This library never canonicalizes it; that's left to whatever ingests the logs downstream. |
| `service` | The service name passed to `configure_logging()` / `log_event()`. |
| `event` | A short, stable, dot-namespaced string (`batch.completed`, `run.failed`) — the thing a dashboard panel or an alert actually filters on. |
| `msg` | Human-readable prose for a person reading the log — never what anything alerts on. |
| *(extra fields)* | Anything else the caller passes — `run_id`, `outcome`, `items_processed`, `err_type`, `err_msg`, `duration_ms`, etc. |

On an exception (`exc_info` set), `err_type` is filled in automatically if
the caller didn't already supply one.

### Redaction

Both `configure_logging()`/`log_event()` redact known secret-shaped field
names before a line is emitted, as defense-in-depth on top of whatever the
log pipeline downstream does. Deny-listed keys (case-insensitive match):

```
password, passwd, token, api_key, apikey, secret, authorization,
access_token, refresh_token, ssn, cookie, session
```

A matching key's value is replaced with `[REDACTED]`. Independently, any
string value that parses as a URL with a query string has the query string
stripped — query strings carry API keys and session tokens far more often
than path segments do.

Residual gap, stated rather than hidden: a secret value logged under an
unlisted or misspelled key name still reaches the log line. This closes the
common case, not every case.

### Library-vs-application rule

Only an application's own entry point calls `configure_logging()`. Every
importable module should use `logging.getLogger(__name__)` (or call
`log_event()` directly) and never touch a handler, formatter, or
`basicConfig` itself — that's what keeps two libraries from fighting over
who owns the root logger's output.

## What it replaces

Extracted from, and a strict superset of, several internal Python services
that had each independently hand-rolled the same JSON logging shape — one
as a `logging.Formatter` subclass with an idempotent `configure_logging()`,
another as a standalone `log_event()` function with no `logging` module
dependency plus its own field redaction — and two independently hand-rolled
yaml+env config loaders with slightly different missing-file behavior (see
"Config loading" below).

## Using it

**stdlib `logging`-based** (an application with a long-lived process):

```python
import logging
from fleet_logging import configure_logging

configure_logging("my-service")  # call once, at the entry point only
log = logging.getLogger(__name__)
log.info("batch complete", extra={"event": "batch.completed", "run_id": run_id,
                                   "outcome": "ok", "items_processed": 42})
```

**Direct function call** (a oneshot CLI invocation with no long-lived
process to configure):

```python
from fleet_logging import log_event, new_run_id

run_id = new_run_id()
log_event("info", "batch.completed", service="my-service", run_id=run_id,
           outcome="ok", items_processed=42)
```

**Config loading**:

```python
from dataclasses import dataclass, field
from fleet_logging import load_config

@dataclass
class Config:
    db_path: str = "data/db.sqlite"
    review_min_days: int = 7
    symbol_universe: list[str] = field(default_factory=list)

cfg = load_config(Config, "config.yaml")  # yaml -> env override -> field default
```

`load_config()` overlays, highest precedence first: an environment variable
(`{env_prefix}{FIELD}`, uppercased) > a value from the yaml file > the
dataclass field's own default. Pass `required=True` if a missing yaml file
should be fatal (`FileNotFoundError`) instead of falling back to
defaults/env with a logged warning.

## Adding it as a dependency

Pinned to an exact commit — a floating branch/tag ref is deliberately
avoided so a consumer never picks up an untested change:

```toml
dependencies = [
    "fleet-logging @ git+ssh://git@github.com/preston-bernstein/fleet-logging.git@40b6e439d453d40e407baba5959631caf60f5e7b",
]
```

Bump the pin by hand when a consumer wants a newer commit — no package
registry, solo-maintainer workflow.

## Stack

| Layer | Tech |
|---|---|
| Language | Python 3.11+ |
| Build | Hatchling |
| Tests | pytest 8+ |
| Lint | ruff |
| Config parsing | PyYAML, python-dotenv |

## Project layout

```
src/fleet_logging/
├── __init__.py       # public re-exports
├── formatter.py       # JsonFormatter, configure_logging, log_event, new_run_id
├── redact.py           # deny-list + redact_fields()
└── config.py            # load_config(dataclass_type, path)
tests/                    # one test module per source module
```

## Quick start

```bash
git clone git@github.com:preston-bernstein/fleet-logging.git
cd fleet-logging
pip install -e ".[test,dev]"
pytest
```

## Environment variables

This library reads no environment variables of its own. `python-dotenv` is
a dependency of `load_config()` only, so that a `.env` file's values (if a
*consumer* has one) participate in the same env-override precedence as any
other environment variable — see `.env.example`.

## License

MIT — see [LICENSE](LICENSE).
