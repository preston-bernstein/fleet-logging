# fleet-logging

This is a shared library, meant to be **imported** by home-lab repos, not run
on its own. It implements home-infra's `CONVENTIONS.md` §18 fleet JSON
logging contract for real, in Python, plus a small `load_config` yaml+env
config-loader helper.

It replaces three independently hand-written implementations of the same
§18 contract (`algo-corpus/src/corpus_pipeline/logging_setup.py`,
`algo-macro-monitor/src/macro_monitor/log.py`, and financial-pipeline's
TypeScript `packages/adapter-utils/src/logger.ts` — TS is out of scope here,
someone can port it later) and two independently hand-written yaml+env config
loaders (`algo-macro-monitor/src/macro_monitor/config.py`,
`algo-corpus/src/corpus_pipeline/config.py`). See
`home-infra/docs/adr/0023-dedicated-lib-repos-for-fleet-logging-and-ollama-client.md`
for why this lives in its own repo rather than inside `home-infra` itself,
and the vault doc `Development/Research/algo-repo-modularization.md` for the
original duplication finding.

Cross-cutting home-lab conventions that apply here too — service users,
secrets, the split between a shared library (this repo) and a shared
service, and the §18 contract text itself — live in
`home-infra/CONVENTIONS.md`. The decision to build shared libraries this way
(imported and versioned, dedicated repo per library, following the
`scraper-commons`/ADR-0015 pattern) is recorded in
`home-infra/docs/adr/0015-shared-scraper-library.md` and extended by
ADR 0023 above for this specific repo.

## Remotes

A single `git push` to `origin` writes to two remotes: the NAS (primary,
`ssh://nas-agent/.../fleet-logging.git`) first, then GitHub (offsite mirror,
`preston-bernstein/fleet-logging`, private) second. `git fetch` only reads
from the NAS.

## Implemented on first extraction, not speculatively

Both modules (`formatter.py`'s JSON log line + `config.py`'s `load_config`)
were extracted from the three/two existing hand-rolled implementations
listed above, not designed ahead of a consumer — see each module's own
docstring for exactly which behaviors were carried over from which source
file. A future field/behavior addition should be grounded in a real
consumer's need the same way, not spec'd speculatively.
