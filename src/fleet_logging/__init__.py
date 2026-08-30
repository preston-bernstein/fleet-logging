"""fleet-logging — a home lab's shared implementation of one canonical JSON
logging contract (log line shape, level vocabulary, redaction, correlation)
plus a small `load_config` helper for the yaml+env config-loading pattern
several internal services hand-rolled separately.

Built by extracting from several existing hand-written implementations
across those services, so this package is a strict superset of what they
actually did, not a fresh reinterpretation of a spec written in a vacuum.
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
