---
type: project_topic
status: active
summary: "Inventory of the project knowledge that existed before Project Cairn — where each kind of question is already answered, and what each document may and may not be trusted for."
tags: [analog-studio, documentation, inventory]
contains: [reference]
created: "2026-08-18"
updated: "2026-08-18"
related: [pitfalls]
authoring_mode: ai_generated
---
# Existing knowledge (pre-Cairn inventory)

Cairn was initialized with `migration_mode: inventory_only`: the documents
below are **not** rewritten or absorbed into `cairn/`. This note is the map,
so a newcomer does not re-derive what is already written down.

## Where to look first

| Question | Document |
|---|---|
| What is this and how do I run it? | `README.md` / `README.zh-CN.md` |
| How is the app built, packaged, laid out? | `APP_README.md` |
| How do I develop, test, lint, release? | `CONTRIBUTING.md` |
| What is still open, and who is it blocked on? | `ROADMAP.md` (repository root) |
| What changed in a release, and why? | `CHANGELOG.md` |
| What do the Nuitka builds actually protect? | `CODE_PROTECTION.md` |
| How do I use the application? | In-app manual, F1 (English + Chinese) |
| What are the traps in this codebase? | `cairn/pitfalls.md` |

## Historical documents — read with their dates

Three analysis reports are **snapshots, not current-state descriptions**. Each
carries its own vendor/analysis date in its header, and each says so; they are
kept as records of what was true when a decision was made.

| Document | Analysed | Subject |
|---|---|---|
| `ANALYSIS_REPORT.md` | 2026-07-07 | The upstream `gmoverid-skill` repository at vendor time |
| `CIRCUIT_SKILLS_ANALYSIS.md` | 2026-07-09 | `analog-circuit-skills` + a GUI-integration assessment |
| `ANALOG_REPOS_ANALYSIS.md` | 2026-07-10 | AnalogCoder / Analogagent / AnalogGym compared, plus the design proposal that became the Sizing tab |

Known drift, deliberately left in place: `ANALOG_REPOS_ANALYSIS.md` §6.3
proposes `app/core/sizing.py` at "~400 lines" using differential evolution.
That was the plan on 2026-07-10. The module was built, grew to 1638 lines, and
was split into a package on 2026-08-11. The document is a record of the
proposal, not a description of the result — do not "correct" it.

`analoggym/README.md` also still points at `app/core/sizing.py`, which is now a
package. It sits inside a vendored tree this project does not modify, so the
stale path is tracked as an open item in `ROADMAP.md` rather than fixed
quietly.

## What is authoritative

- **Code beats every document.** The version is `app/__init__.py`; the circuit
  registry is `app/core/sizing/registry.py`; the build commands that are known
  to work are the ones in `.github/workflows/`, not the abbreviated forms in
  `APP_README.md`.
- **`CHANGELOG.md` is the event ledger** for shipped behaviour, and its v1.4
  section is marked *unreleased* because no tag has ever been cut.
- **`ROADMAP.md` holds open work**, including a *Decided against* section —
  check it before "fixing" something that was settled on purpose.
