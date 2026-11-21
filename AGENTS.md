# Rules for agents

fleet-logging is a Python library: one JSON log format and one config loader. It has no Nx tags or package map. Code lives in `src/fleet_logging/`, tests in `tests/`.

## Commands

- The one gate: `bash scripts/core-validate.sh` (file size, names, complexity, function length, parameters, nesting, duplication). Run it before you say a task is done.
- Install the pinned gate tools once: `bash scripts/install-gate-tools.sh`, then run the `export PATH=...` line it prints.
- Install the project: `uv sync` (dev group included). Run anything with `uv run <command>`. Never `pip install` into the environment.
- Python gate: `bash scripts/py-validate.sh` (`uv run --locked` ruff check, ruff format --check, mypy, pytest).
- Workflow gate: `bash scripts/gha-validate.sh` (workflow-check.py, actionlint, zizmor).
- Writing gate: `bash scripts/writing-validate.sh` (Vale on changed files).
- Add a dependency: `uv add <pkg>` or `uv add --dev <pkg>`. Ask before you add a production dependency.
- Hook: `git config core.hooksPath .githooks`. It runs all four gates. CI runs the same four. Never commit with `--no-verify`.

## Core rules

- Reuse before you write. Search for an existing function or module first. Extend it instead of adding a near copy.
- Put variants in data and in generic code, not in copies. Extract on the second real occurrence, not the first guess.
- No boolean flag arguments. Two behaviors are two functions.
- Organize by domain. Do not organize by kind (utils, helpers, managers). Dependencies point one way: edge to domain, never back.
- A function does one thing. Use guard clauses. Keep it under 50 lines, under 10 branches, at most 4 parameters.
- Names say what a thing is or does. No `data`, `info`, `tmp`, `handle`, `process` as a whole name.
- Fail loudly: raise an error with context. Never swallow one. Comments say why, not what. Delete dead code.
- A behavior change ships with a test that fails without it.
- Never edit a limit or a config to make a run pass. Fix the code. A waiver goes in `.core-allow` with a reason.
- `.core-baseline.json` lists old over-limit functions. It may shrink. It must never grow.

## Python rules

- Fix what a tool reports. Do not add an `ignore` to pyproject.toml. A one-line exception is `# noqa: CODE -- reason` or `# type: ignore[code]  # reason`.
- New code is fully typed (mypy strict). Public functions have a docstring line.
- Catch the narrowest exception. Never `except:` or a silent `pass`.
- Library code logs with `log = logging.getLogger(__name__)` and `log.info("x=%s", x)`. Only `log_event` prints, by design.

## GitHub Actions rules

- Pin every `uses:` to a full 40-character commit SHA with the version in a trailing comment. Dependabot moves them.
- Set `permissions: contents: read` at the top of every workflow. Raise it per job only where needed.
- Never put `${{ github.event... }}`, `${{ github.head_ref }}` or `${{ inputs.x }}` inside `run:`. Pass it through `env:`.
- No `pull_request_target`. `actions/checkout` gets `persist-credentials: false`. Every job has `timeout-minutes`. No `secrets: inherit`.
- Never edit the workflow checks or the zizmor config to make a run pass.

## Writing rules

- Docs and comments are short, plain, American English. Put the point first. Put the condition first: "If the build fails, run X".
- No filler words or stock AI phrasing. The banned list is in `scripts/styles/House`. A false positive gets `<!-- vale off -->` with a reason, or a line in `.writing-allow`.

## Traps

- `scripts/` holds unchanged copies from the stack packs, except `install-gate-tools.sh`. Do not edit them. Ruff and the core gate skip them on purpose.
- Tool versions are pinned in one place each: `ci/gate-tools/` (lizard, zizmor, jscpd), `scripts/install-gate-tools.sh` (vale, actionlint) and `uv.lock` (ruff, mypy, pytest). Change a pin and its lock together.
- `scripts/styles` and `scripts/vale-central.ini` are copies of the writing pack config (central mode). Do not edit it.
