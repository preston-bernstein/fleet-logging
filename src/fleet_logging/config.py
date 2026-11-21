"""`load_config(dataclass_type, path)` — a yaml + environment config loader.

Extracted from, and a strict superset of, two hand-rolled loaders this
package replaces from separate internal services:

- One: a flat dataclass, a `config.yaml` overlay, **non-fatal** on a missing
  file (falls back to dataclass defaults, logging a warning with the
  resolved path it tried), **fatal** (re-raised, after logging) on a
  malformed file.
- The other: **fatal** (`FileNotFoundError`) on a missing config file, loads
  secrets from a `.env` file via `python-dotenv` rather than `config.yaml`
  (so a secret never lands in a checked-in-adjacent yaml file).

Both missing-file behaviors are preserved here via `required=` — default
`False` (the forgiving behavior) since that is the more conservative default
for a brand-new consumer; a consumer that wants the other service's
"config file is mandatory" behavior passes `required=True`.

This module does **not** attempt to reproduce either source service's own
config shape (one had a raw dict plus a nested dataclass list plus computed
`Path`-joining properties) — that is domain-specific to that service, not
part of the generic yaml+env+dataclass contract every consumer shares. What
this module guarantees is that the *mechanism* each original relied on
(secrets from `.env`/environment, never from the yaml file; yaml overlay
onto dataclass defaults with a non-fatal missing file) is expressible
without dropping behavior.
"""

from __future__ import annotations

import os
import types
import typing
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

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


def _unwrap_optional(annotation: object) -> object:
    """`int | None` / `Optional[int]` -> `int`. Leaves everything else
    unchanged, including plain `list`/`list[str]`."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _parse_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in _TRUE_STRINGS:
        return True
    if lowered in _FALSE_STRINGS:
        return False
    raise ValueError(f"{raw!r} is not a recognized boolean")


def _split_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _identity(raw: str) -> str:
    return raw


# Add a supported field type by adding a row here.
_CONVERTERS: dict[object, Callable[[str], object]] = {
    bool: _parse_bool,
    int: int,
    float: float,
    list: _split_list,
}


def _converter_for(annotation: object) -> Callable[[str], object]:
    key = typing.get_origin(annotation) or annotation
    try:
        return _CONVERTERS.get(key, _identity)
    except TypeError:  # an unhashable annotation has no converter
        return _identity


def _coerce(raw: str, annotation: object, field_name: str) -> object:
    annotation = _unwrap_optional(annotation)
    try:
        return _converter_for(annotation)(raw)
    except ValueError as exc:
        raise ConfigError(
            f"env override for field {field_name!r} ({raw!r}) could not be "
            f"coerced to {annotation!r}: {exc}"
        ) from exc


def _read_yaml(path: str | os.PathLike[str] | None, required: bool, service: str) -> dict[str, Any]:
    """Return the yaml mapping, or `{}` when there is no file to read."""
    if path is None:
        return {}
    cfg_path = Path(path)
    if not cfg_path.exists():
        return _handle_missing_file(cfg_path, required, service)
    try:
        return yaml.safe_load(cfg_path.read_text()) or {}
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


def _handle_missing_file(cfg_path: Path, required: bool, service: str) -> dict[str, Any]:
    if required:
        raise FileNotFoundError(f"{cfg_path} missing and required=True was passed to load_config()")
    log_event(
        "warn",
        "config.missing",
        "config file not found, falling back to defaults/env",
        service=service,
        path=str(cfg_path.resolve()),
    )
    return {}


def _field_overrides(
    dataclass_type: type[Any],
    yaml_values: dict[str, Any],
    env_prefix: str,
    path: str | os.PathLike[str] | None,
) -> dict[str, Any]:
    type_hints = typing.get_type_hints(dataclass_type)
    kwargs: dict[str, Any] = {}
    for f in fields(dataclass_type):
        env_key = f"{env_prefix}{f.name}".upper()
        if env_key in os.environ:
            kwargs[f.name] = _coerce(os.environ[env_key], type_hints.get(f.name, str), f.name)
        elif f.name in yaml_values and yaml_values[f.name] is not None:
            kwargs[f.name] = yaml_values[f.name]
        elif f.default is MISSING and f.default_factory is MISSING:
            raise ConfigError(
                f"field {f.name!r} has no default and was not present in "
                f"{path!r} or the environment"
            )
    return kwargs


def load_config(
    dataclass_type: type[T],
    path: str | os.PathLike[str] | None = None,
    *,
    required: bool = False,
    env_prefix: str = "",
    dotenv_path: str | os.PathLike[str] | None = None,
    service: str = "fleet-logging",
) -> T:
    """Load a flat dataclass config from a yaml file overlaid with
    environment variables (and a `.env` file, loaded first so its values
    participate in the same environment overlay).

    Precedence, highest first: environment variable (`{env_prefix}{FIELD}`,
    uppercased) > yaml file value > the dataclass field's own default.

    `required=False` (default): a missing yaml file is non-fatal — logs a
    `config.missing` warning with the resolved path and falls back to
    defaults/env overrides only. A yaml file that exists but fails to parse
    is always fatal (logs `config.parse_failed`, then re-raises) in either
    mode — a malformed config is a genuine operator error, not something to
    silently default around.

    `required=True`: a missing yaml file raises `FileNotFoundError`.
    """
    if not is_dataclass(dataclass_type):
        raise TypeError(f"{dataclass_type!r} is not a dataclass")

    load_dotenv(dotenv_path) if dotenv_path else load_dotenv()

    yaml_values = _read_yaml(path, required, service)
    return dataclass_type(**_field_overrides(dataclass_type, yaml_values, env_prefix, path))
