# fleet-logging

fleet-logging is a Python library that gives every service in a home lab one JSON log format and one config loader. Before it existed, several services each wrote their own copy of the same logging code, and the copies drifted apart.

It is a library, not a service. A consumer imports it. It has two parts: logging (`configure_logging`, `log_event`, `new_run_id`) and config (`load_config`).

## Every log line is one JSON object

These fields appear on every line:

| Field | Meaning |
|---|---|
| `schema_version` | Integer, now `1`. Raise it when the shape changes. |
| `ts` | UTC time, format `%Y-%m-%dT%H:%M:%SZ`. |
| `level` | The caller's own spelling. `log_event()` takes `debug`, `info`, `warn`, `error`, `critical`. stdlib `logging` gives `DEBUG`, `INFO`, and so on. The library never changes it. |
| `service` | The name you pass to `configure_logging()` or `log_event()`. |
| `event` | A short, stable, dot-separated name such as `batch.completed`. Dashboards and alerts filter on it. |
| `msg` | Text for a person. Never alert on it. |

Any extra field you pass, such as `run_id` or `items_processed`, is added to the line. If a log call carries an exception and you gave no `err_type`, the library sets `err_type` to the exception class name.

## Log from a service

Use stdlib `logging` in a long-running process. Call `configure_logging` once, in the entry point only.

```python
import logging
from fleet_logging import configure_logging

configure_logging("my-service")
log = logging.getLogger(__name__)
log.info(
    "batch complete",
    extra={"event": "batch.completed", "run_id": run_id, "outcome": "ok", "items_processed": 42},
)
```

Use `log_event` in a short CLI run that has nothing to configure.

```python
from fleet_logging import log_event, new_run_id

run_id = new_run_id()
log_event(
    "info", "batch.completed", service="my-service", run_id=run_id, outcome="ok", items_processed=42
)
```

Both write to stdout by default. Pass `stream=sys.stderr` to change that.

Library modules must not call `configure_logging()`, set handlers, or call `basicConfig`. They call `logging.getLogger(__name__)` or `log_event()`. This stops two libraries from fighting over the root logger.

`new_run_id()` returns `$RUN_ID` if it is set. Otherwise it returns an id like `run-20261114T120000Z-1a2b3c4d`. A shell script can set `RUN_ID` so its Python child shares the id.

## Secret fields are redacted

The library replaces the value with `[REDACTED]` for these keys, matched without regard to case:

```
password, passwd, token, api_key, apikey, secret, authorization,
access_token, refresh_token, ssn, cookie, session
```

It also removes the query string from any string value that is a URL. Query strings often hold API keys.

A secret under any other key name still reaches the log. Redaction here is a second layer. The log pipeline should redact too.

## Load config from yaml and env

```python
from dataclasses import dataclass, field
from fleet_logging import load_config


@dataclass
class Config:
    db_path: str = "data/db.sqlite"
    review_min_days: int = 7
    symbol_universe: list[str] = field(default_factory=list)


cfg = load_config(Config, "config.yaml")
```

Precedence, highest first:

1. Environment variable `{env_prefix}{FIELD}`, in upper case. `env_prefix` defaults to an empty string.
2. Value in the yaml file.
3. Default on the dataclass field.

Details:

- The loader reads a `.env` file first, so its values count as environment variables. Pass `dotenv_path` to choose the file.
- Env values are cast to the field type: `bool`, `int`, `float`, or `list` (comma separated). A bad value raises `ConfigError`.
- A field with no default and no value raises `ConfigError`.
- A missing yaml file logs a `config.missing` warning and uses defaults. Pass `required=True` to raise `FileNotFoundError` instead.
- A yaml file that fails to parse always raises.

## Add it to a project

Pin an exact commit. A branch or tag could pull in an untested change.

```toml
dependencies = [
    "fleet-logging @ git+ssh://git@github.com/preston-bernstein/fleet-logging.git@<commit-sha>",
]
```

Change the pin by hand when you want a newer commit. There is no package registry.

## Set up for development

1. Run `git clone git@github.com:preston-bernstein/fleet-logging.git`.
2. Run `cd fleet-logging`.
3. Run `uv sync`.
4. Run `bash scripts/install-gate-tools.sh`, then run the `export PATH=...` line it prints.
5. Run `git config core.hooksPath .githooks`.
6. Run `bash scripts/py-validate.sh`.

The hook and CI run four gates: `core-validate.sh`, `gha-validate.sh`, `py-validate.sh` and `writing-validate.sh`, all in `scripts/`.

It needs Python 3.11 or newer. Dependencies are PyYAML and python-dotenv.

## Where things live

- `src/fleet_logging/formatter.py`: `JsonFormatter`, `configure_logging`, `log_event`, `new_run_id`.
- `src/fleet_logging/redact.py`: the deny-list and `redact_fields()`.
- `src/fleet_logging/config.py`: `load_config` and `ConfigError`.
- `tests/`: tests for the formatter and the config loader.

License: MIT. See [LICENSE](LICENSE).
