# Project Cairn Log

This file records substantive progress in reverse-chronological order — newest entry at the top, right below this line. Keep each entry short — summary and pointer only; conclusions settle into `cairn/<topic>.md`.

## 2026-09-10 · Imported netlists could execute shell commands — fixed

- ngspice runs `.control` blocks in batch mode; imported netlists **and**
  their `.PARAM` files are `.include`d verbatim, and directives inside an
  included file execute the same. Reproduced end to end: payload ran, the
  metric report looked normal.
- Guard added at both registration paths — `import_user_circuit()` refuses a
  control block in either file, `load_user_circuits()` re-checks files
  already on disk instead of trusting them.
- 6 regression tests, including one that asserts ngspice really does execute
  the payload, so the guard cannot quietly become pointless.
- Details: `cairn/pitfalls.md` → "A netlist is code"; residual `.include`
  file-read issue tracked in `ROADMAP.md`.

## 2026-08-18 · Project Cairn initialized

- Initialized Project Cairn structure: `AGENTS.md`, one-line `CLAUDE.md`, `.cairn/config.yaml`, this log.
- `git_policy: track` — `cairn/` is committed. The repository is public, so nothing client-private or personally sensitive may be written here.
- Graduation provider deferred (`provider: none`); collected at the first graduation instead.
- Historical migration mode: `inventory_only`. The pre-Cairn documentation is inventoried in `cairn/existing-knowledge.md`, not rewritten.
- `ROADMAP.md` stays at the repository root rather than moving to `cairn/`: it predates Cairn by one day and is already linked from `README.md`, `README.zh-CN.md` and `CONTRIBUTING.md`. `AGENTS.md`'s reading order points at the root file.
- The previous 96-line `CLAUDE.md` was not discarded — its rules moved into `AGENTS.md` and its five failure modes into `cairn/pitfalls.md`. Details: see `AGENTS.md` and `.cairn/config.yaml`.
