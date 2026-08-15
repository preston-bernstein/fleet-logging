# Maintainability polish — 2026-08-14

Full polish pass over this repo. Auto-apply was pre-authorized, with an
explicit conservative carve-out for the public API surface
(`configure_logging`, `log_event`, `load_config`, and anything else exported
from `fleet_logging/__init__.py`) given three live pinned consumers
(algo-corpus, algo-macro-monitor, nba-predictor). Rubric: Google's
eng-practices review doc (architecture/readability baseline, archived
2025-11-21) plus this repo's own dogfooding bar — its whole purpose is
observability tooling for other repos, so it was held to a high bar on its
own silent-failure surface.

## Starting state

- `git fetch origin` — already up to date with `origin/main`, nothing to pull.
- `git status --porcelain` — clean working tree before this pass started.
- Baseline: `ruff check .` clean, `pytest` 29/29 passing.
- Repo size: 4 source modules (`__init__.py`, `config.py`, `formatter.py`,
  `redact.py`), ~450 lines total. Small and already well-documented — this
  pass found few issues, as expected for a mature, actively-consumed library.

## Deterministic dead-code signal

`deadcode` and `skylos` were not preinstalled; `deadcode` was skipped per the
standing note that it can crash on Python 3.14 (`ast.Str` removal) — this
Mac's system Python is 3.14.6. Installed `skylos` into the repo's own `.venv`
and ran it, cross-checked with `vulture` (already on PATH).

- **skylos**: grade A- (92/100), 1 flagged item — `value` parameter on
  `_StreamHandler`'s `stream` setter (`formatter.py:114`), 90% confidence.
  **Not removed** — this is a deliberate no-op override required by the base
  `logging.StreamHandler` class (the docstring above it explains why:
  `configure_logging()` must stay idempotent against a re-entrant call, but
  the base class still expects a working `stream` setter to exist). Also
  flagged a 1-module "circular dependency" (`fleet_logging` → `fleet_logging`,
  length 1) — a false positive from `config.py` importing a sibling module
  via the package's own absolute path (`from fleet_logging.formatter import
  log_event`), not a real cycle.
- **vulture**: 1 item — `JsonFormatter.format` "unused" at 60% confidence.
  False positive: it's a `logging.Formatter` override, invoked polymorphically
  by the stdlib `logging` framework, not by anything in this repo.

Net: **zero real dead code**. Consistent with a small, mature library.

## Applied (auto-apply lane)

All of the following are internal-only or additive-only to the exported
surface — no existing consumer's imports or call signatures change.

| # | Change | File | Why |
|---|---|---|---|
| 1 | Re-export `ConfigError` from the package root | `src/fleet_logging/__init__.py` | `load_config()` raises `ConfigError` on a malformed env override or a missing required field with no default, but the type was only reachable via `fleet_logging.config.ConfigError`, not the public `fleet_logging` namespace every other exported symbol uses. A consumer that wants to `except` it had to reach into the submodule. Adding a new export doesn't change any existing symbol's behavior — unambiguously additive. |
| 2 | Add missing type hints on `stream` params | `src/fleet_logging/formatter.py` — `configure_logging`, `log_event`, `_StreamHandler.__init__` | `stream` was untyped (just `=None`) on both public functions. Added `stream: TextIO \| None = None` (and `TextIO` on the private `_StreamHandler`). Annotations only — `from __future__ import annotations` means these were never evaluated at runtime anyway; zero behavior change. This is the literal "adding a missing type hint" example given as an allowed additive fix. |
| 3 | Add type hints to private helpers | `src/fleet_logging/config.py` — `_unwrap_optional`, `_coerce` | Neither is exported; added `object` param/return hints for readability. No behavior change. |
| 4 | Regression test for the new export | `tests/test_config.py` | Added `TestConfigErrorReExport` asserting `fleet_logging.ConfigError is ConfigError` from the submodule, so the re-export has coverage rather than being an untested doc claim. |

Removed a `.skylos/` tool-cache directory the dead-code run created; not
committed (matches `.pytest_cache/`/`.ruff_cache/` already being gitignored
tool artifacts, though this one wasn't even added).

## Escalated — not applied

Per the explicit instruction that any *behavior* change to the public API
surface must be escalated even if judged safe (not just signature changes),
three items were found and deliberately left untouched:

### 1. `load_config`: real bug in `Optional`/PEP 604 union coercion

`config.py`'s `_unwrap_optional()` checks:

```python
origin = typing.get_origin(annotation)
if origin is typing.Union:
```

This only matches classic `typing.Optional[int]` / `typing.Union[int, None]`
syntax. On Python 3.11–3.13 (this repo targets `>=3.11`; CI pins exactly
3.11), `typing.get_origin(int | None)` returns `types.UnionType`, which is
**not** `is typing.Union` — confirmed empirically against the Homebrew 3.12
and 3.13 interpreters on this machine (both return `types.UnionType`,
`is typing.Union` is `False`). Only on this Mac's system Python 3.14 do the
two objects happen to unify, which is why this didn't surface during
ordinary local testing here — it's real on the versions that actually matter
(3.11–3.13, i.e. everything this library and its CI target).

**Effect**: a consumer dataclass field typed `int | None` (the modern
syntax, not `Optional[int]`) does **not** get env-var coercion — `_coerce()`
receives the raw union type, matches none of its `bool`/`int`/`float`/`list`
branches, and silently returns the *raw string* uncoerced. This is exactly
the kind of silent failure this repo's own observability mandate exists to
prevent, and it contradicts `_unwrap_optional`'s own docstring, which
explicitly promises `int | None` support.

This is a genuine bug fix, not a new feature, and the current behavior is
almost certainly not something any consumer intentionally depends on. But it
changes `load_config`'s actual coercion behavior for a real input shape, so
per the explicit "any public API behavior change → escalate" rule, it is
**not applied**. Recommended fix, if approved:

```python
import types
...
origin = typing.get_origin(annotation)
if origin in (typing.Union, types.UnionType):
```

### 2. `load_config`: missing-required-file path has no log line before raising

Every other fatal path in `load_config` logs a structured `log_event` before
raising (`config.parse_failed` on malformed YAML; `config.missing` warning
on the non-fatal missing-file case). The `required=True` missing-file path
raises `FileNotFoundError` directly with no log line at all — inconsistent
with the rest of the module and a real gap for an operator relying on the
JSON-log stream (stdout) rather than a captured stderr traceback. Same
question applies to the two `ConfigError` raise sites (bad env coercion in
`_coerce`, missing field with no default) — neither logs before raising.

Not applied: adding a log line before an existing raise doesn't change the
exception type or message, but it is still a behavior change (a new
side-effecting log emission) to a function three repos call directly, so it
falls under "escalate" per instruction. If approved, the fix is small: mirror
the existing `config.parse_failed` pattern at the `required` branch and wrap
the coercion/missing-field raises the same way.

### 3. `JsonFormatter.format`: exception path captures `err_type` but not `err_msg`

When a `LogRecord` carries `exc_info` (e.g. from `logger.exception(...)`),
`JsonFormatter.format()` adds `err_type` to the JSON line but never
`err_msg` — the actual exception message. `log_event()`'s own docstring
lists `err_type`/`err_msg` as the canonical §18 pair, and a caller using the
manual `log_event()` path gets both if they pass them; a caller using the
stdlib-`logging` + `JsonFormatter` path only gets `err_type` automatically.
This is an asymmetry between the two documented "two usage shapes," and a
real diagnostic gap (an operator sees *that* something raised `ValueError`
but not what the message said).

Purely additive to the JSON output (a new field, nothing removed or
renamed), and no existing consumer could break from gaining a field. Still
not applied, because it changes what `JsonFormatter` — an exported symbol —
actually emits, and the instruction is explicit that any public-API behavior
change gets escalated regardless of how safe it looks. Recommended fix, if
approved:

```python
if record.exc_info and "err_type" not in line:
    exc_type, exc_value, _ = record.exc_info
    line["err_type"] = exc_type.__name__ if exc_type else "Exception"
    if exc_value is not None:
        line["err_msg"] = str(exc_value)
```

## Judgment pass — architecture/DRY/readability

No `MUST`/`SHOULD` findings. Considered and explicitly declined:

- `JsonFormatter.format()` and `log_event()` build superficially similar
  line dicts (`schema_version`/`ts`/`level`/`service`/`event`/`msg`). Not
  extracted into a shared helper — the module docstring documents these as
  two deliberately distinct usage shapes (stdlib-`logging`-based vs.
  no-process-oneshot), their field sources differ enough (`record.levelname`
  vs. a raw caller string; `record.created` vs. wall-clock `time.gmtime()`)
  that a shared helper would mostly just be parameter-passing, and this is
  the most safety-critical code path in the package — not worth the risk for
  a ~5-line saving.
- `load_config()` is ~35 logical lines and does several things (dotenv load,
  yaml read, per-field env/yaml/default resolution), but it's a single
  cohesive responsibility (load one config), well-commented, and splitting it
  further would be new abstraction not implied by any current need — YAGNI.

## Judgment pass — observability/dogfooding

Covered above (the three escalated items are exactly this lens's findings).
Everything else already dogfoods well: `json.dumps(..., default=str)` is
used consistently in both emission paths so a non-serializable extra field
never crashes the logger itself; `configure_logging()`'s idempotency check
is keyed on the handler *type*, not `root.handlers` truthiness, specifically
to avoid falsely treating a test runner's unrelated pre-attached handler as
"already configured" (a bug class the code's own comment calls out);
`redact_fields()` degrades gracefully (best-effort `urlsplit`, falls through
unchanged on a non-URL string) rather than raising on odd input.

## Regression safety net

`ruff check .` and `pytest` both run clean before and after all applied
changes: **30/30 tests passing** (29 pre-existing + 1 new), zero lint
findings.

## Standards used

- Google eng-practices code review doc — architecture/readability rubric
  baseline (archived/frozen 2025-11-21).
- `skylos` (installed into `.venv` for this run) + `vulture` — Python
  dead-code signal; `deadcode` skipped (known Python-3.14 `ast.Str` crash
  risk, and this machine's system Python is 3.14.6).
- No Python duplication tool specified — judgment call given the repo's
  small size (~450 lines across 4 modules).
- home-infra `CONVENTIONS.md` §18 (the fleet logging contract this package
  implements) — the ground truth for what "correct" observability behavior
  is, cited throughout this repo's own docstrings already.

## Not in scope

Consumers (algo-corpus, algo-macro-monitor, nba-predictor) all pin to a
specific commit and won't see any of this until someone bumps their pin by
hand — that bump is out of scope for this pass.
