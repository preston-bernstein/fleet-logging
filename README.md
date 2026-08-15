# fleet-logging

fleet-logging is a shared Python library for the home lab's fleet of
services (algo-corpus, algo-macro-monitor, financial-pipeline, algo-factory,
…). It implements home-infra's `CONVENTIONS.md` §18 fleet JSON logging
contract for real, so each repo imports one canonical implementation
instead of hand-writing its own JSON formatter and drifting out of sync with
the spec — which is exactly what happened before this package existed:
three repos independently reimplemented the same §18 contract.

[![CI](https://github.com/preston-bernstein/fleet-logging/actions/workflows/ci.yml/badge.svg)](https://github.com/preston-bernstein/fleet-logging/actions/workflows/ci.yml)  [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab)](pyproject.toml)  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Library, not a service

fleet-logging is a library, not a running service — a consumer *imports* it
directly. See `home-infra/CONVENTIONS.md` §8 and
`home-infra/docs/adr/0015-shared-scraper-library.md` for the shared-service-
vs-shared-library split this repo follows, and
`home-infra/docs/adr/0023-dedicated-lib-repos-for-fleet-logging-and-ollama-client.md`
for why this specific library got its own repo.

## What it replaces

Extracted from, and a strict superset of, three hand-written implementations
of the same §18 contract:

- `algo-corpus/src/corpus_pipeline/logging_setup.py` — a `logging.Formatter`
  subclass + idempotent `configure_logging()`.
- `algo-macro-monitor/src/macro_monitor/log.py` — a standalone `log_event()`
  function with no `logging` module dependency, plus field redaction.
- `financial-pipeline/packages/adapter-utils/src/logger.ts` — TypeScript,
  out of scope for this package (Python only); a TS equivalent can be built
  the same way later.

And two hand-written yaml+env config loaders:
`algo-macro-monitor/src/macro_monitor/config.py`,
`algo-corpus/src/corpus_pipeline/config.py`.

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

Both `configure_logging`/`log_event` redact the home-infra §18 deny-list
(`password`, `token`, `api_key`, `secret`, `authorization`, …) at the point a
line is about to be emitted, as defense-in-depth on top of the shared Loki
pipeline's own redaction backstop.

## Adding it as a dependency

Pinned to an exact commit, matching the `scraper-commons` pattern already in
use — a floating branch/tag ref is deliberately avoided so a consumer never
picks up an untested change:

```toml
dependencies = [
    "fleet-logging @ git+ssh://git@github.com/preston-bernstein/fleet-logging.git@40b6e439d453d40e407baba5959631caf60f5e7b",
]
```

Bump the pin by hand when a consumer wants a newer commit — same
solo-maintainer, no-package-registry approach as `scraper-commons`
(see ADR 0015).

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
├── redact.py           # §18 deny-list + redact_fields()
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

## License

MIT — see [LICENSE](LICENSE).
