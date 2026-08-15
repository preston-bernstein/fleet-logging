"""`load_config(dataclass_type, path)` — a yaml + environment config loader.

Extracted from, and a strict superset of, the two hand-rolled loaders this
package replaces:

- `internal-monitor-service/src/macro_monitor/config.py`: a flat dataclass, a
  `config.yaml` overlay, **non-fatal** on a missing file (falls back to
  dataclass defaults, logging a warning with the resolved path it tried),
  **fatal** (re-raised, after logging) on a malformed file.
- `internal-corpus-service/src/corpus_pipeline/config.py`: **fatal** (`FileNotFoundError`)
  on a missing config file, loads secrets from a `.env` file via
  `python-dotenv` rather than `config.yaml` (so a secret never lands in a
  checked-in-adjacent yaml file).

Both missing-file behaviors are preserved here via `required=` — default
`False` (internal-monitor-service's forgiving behavior) since that is the more
conservative default for a brand-new consumer; a consumer that wants
internal-corpus-service's "config file is mandatory" behavior passes `required=True`.

This module does **not** attempt to reproduce internal-corpus-service's `Config` shape
itself (a raw dict plus a nested `Book` dataclass list plus computed
`Path`-joining properties) — that is domain-specific to internal-corpus-service, not
part of the generic yaml+env+dataclass contract every consumer shares. What
this module guarantees is that the *mechanism* internal-corpus-service relies on (secrets
from `.env`/environment, never from the yaml file) and the *mechanism*
internal-monitor-service relies on (yaml overlay onto dataclass defaults, non-fatal
missing file) are both expressible without dropping behavior.
"""

from __future__ import annotations

import os
import typing
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from typing import TypeVar

import yaml
from dotenv import load_dotenv

from fleet_logging.formatter import log_event

T = TypeVar("T")

_TRUE_STRINGS = {"1", "true", "yes", "on"}
_FALSE_STRINGS = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """Raised when a config file exists but fails to parse, or a dataclass
    field's environment-variable override cannot be coerced to that field's
    declared type."""


def _unwrap_optional(annotation):
    """`int | None` / `Optional[int]` -> `int`. Leaves everything else
    unchanged, including plain `list`/`list[str]`."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _coerce(raw: str, annotation, field_name: str):
    annotation = _unwrap_optional(annotation)
    try:
        if annotation is bool:
            low = raw.strip().lower()
            if low in _TRUE_STRINGS:
                return True
            if low in _FALSE_STRINGS:
                return False
            raise ValueError(f"{raw!r} is not a recognized boolean")
        if annotation is int:
            return int(raw)
        if annotation is float:
            return float(raw)
        origin = typing.get_origin(annotation)
        if annotation is list or origin is list:
            return [item.strip() for item in raw.split(",") if item.strip()]
        return raw
    except ValueError as exc:
        raise ConfigError(
            f"env override for field {field_name!r} ({raw!r}) could not be "
            f"coerced to {annotation!r}: {exc}"
        ) from exc


def load_config(
    dataclass_type: type[T],
    path: str | os.PathLike | None = None,
    *,
    required: bool = False,
    env_prefix: str = "",
    dotenv_path: str | os.PathLike | None = None,
    service: str = "fleet-logging",
) -> T:
    """Load a flat dataclass config from a yaml file overlaid with
    environment variables (and a `.env` file, loaded first so its values
    participate in the same environment overlay).

    Precedence, highest first: environment variable (`{env_prefix}{FIELD}`,
    uppercased) > yaml file value > the dataclass field's own default.

    `required=False` (default): a missing yaml file is non-fatal — logs a
    `config.missing` warning with the resolved path and falls back to
    defaults/env overrides only (internal-monitor-service's behavior). A yaml file
    that exists but fails to parse is always fatal (logs `config.parse_failed`,
    then re-raises) in either mode — a malformed config is a genuine operator
    error, not something to silently default around.

    `required=True`: a missing yaml file raises `FileNotFoundError`
    (internal-corpus-service's behavior).
    """
    if not is_dataclass(dataclass_type):
        raise TypeError(f"{dataclass_type!r} is not a dataclass")

    load_dotenv(dotenv_path) if dotenv_path else load_dotenv()

    data: dict = {}
    if path is not None:
        cfg_path = Path(path)
        if cfg_path.exists():
            try:
                data = yaml.safe_load(cfg_path.read_text()) or {}
            except yaml.YAMLError as exc:
                log_event(
                    "error",
                    "config.parse_failed",
                    service=service,
                    path=str(cfg_path.resolve()),
                    err_type=type(exc).__name__,
                    err_msg=str(exc),
                )
                raise
        elif required:
            raise FileNotFoundError(
                f"{cfg_path} missing and required=True was passed to load_config()"
            )
        else:
            log_event(
                "warn",
                "config.missing",
                "config file not found, falling back to defaults/env",
                service=service,
                path=str(cfg_path.resolve()),
            )

    type_hints = typing.get_type_hints(dataclass_type)
    kwargs: dict = {}
    for f in fields(dataclass_type):
        env_key = f"{env_prefix}{f.name}".upper()
        if env_key in os.environ:
            kwargs[f.name] = _coerce(os.environ[env_key], type_hints.get(f.name, str), f.name)
        elif f.name in data and data[f.name] is not None:
            kwargs[f.name] = data[f.name]
        elif f.default is MISSING and f.default_factory is MISSING:  # type: ignore[misc]
            raise ConfigError(
                f"field {f.name!r} has no default and was not present in "
                f"{path!r} or the environment"
            )
    return dataclass_type(**kwargs)
