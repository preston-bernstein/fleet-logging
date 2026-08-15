"""fleet-logging — the home-lab's shared implementation of internal-infra's
CONVENTIONS.md §18 fleet logging contract (canonical JSON log line, level
vocabulary, redaction, correlation) plus a small `load_config` helper for the
yaml+env config-loading pattern several repos hand-rolled separately.

Built by extracting from three existing hand-written implementations —
internal-corpus-service's `corpus_pipeline/logging_setup.py`, internal-monitor-service's
`macro_monitor/log.py`, and internal-finance-service's TypeScript
`packages/adapter-utils/src/logger.ts` (Python only here; TS stays
hand-rolled until someone ports it) — so this package is a strict superset
of what those three actually do, not a fresh reinterpretation of the spec.
See internal-infra/docs/adr/0023 for the decision to house this as a dedicated
repo rather than inside internal-infra itself.
"""

from __future__ import annotations

from fleet_logging.config import ConfigError as ConfigError
from fleet_logging.config import load_config as load_config
from fleet_logging.formatter import JsonFormatter as JsonFormatter
from fleet_logging.formatter import configure_logging as configure_logging
from fleet_logging.formatter import log_event as log_event
from fleet_logging.formatter import new_run_id as new_run_id
from fleet_logging.redact import REDACT_KEYS as REDACT_KEYS
from fleet_logging.redact import redact_fields as redact_fields

__version__ = "0.1.0"
