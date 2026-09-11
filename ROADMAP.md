# Roadmap

Where this project stands and what is open. This file is the single place
open work is tracked — the repository does not use GitHub Issues as its
primary list, and there are deliberately no `TODO` comments in the code
(a todo buried in a source file is a todo nobody reads).

Completed work belongs in [`CHANGELOG.md`](./CHANGELOG.md), not here. Items
leave this file when they land, except in *Decided against*, which exists so
a settled question is not reopened from scratch.

**Status as of 2026-09-11** — **v1.4 released**, the repository's first
(tag `v1.4`, five packages). CI is green on all six build jobs and on the
three-platform test matrix. `ruff check .` is clean and gated. 119 tests,
~3 min, running real ngspice; coverage of `app/` is 69%.

---

## Blocked on the maintainer

Nothing here can be moved by a contributor; each needs a decision or an
action only the repository owner can take.

- **Confirm the single-file Windows build actually launches.** The
  `nuitka-onefile` job builds the exe and runs it with `--smoke` on a clean
  runner, exit 0 — but a report of "double-click does nothing" on a real
  machine is unresolved. Diagnosing it is now much easier: a startup failure
  writes `%TEMP%\AnalogStudio-crash.txt` and says so in a dialog, and a slow
  first launch shows a splash saying the assets are being unpacked. So the
  three candidate causes are now distinguishable rather than guesswork — a
  crash leaves the file, a slow unpack shows the splash, and SmartScreen
  blocking shows neither. The exe no longer expires either — it is a
  [v1.4 release asset](https://github.com/alexyudragonsword-collab/analog_skill/releases/tag/v1.4)
  now, not a 90-day artifact. Still needs one run on the reporting machine.
- **English one-page overview (16:9).** Outline agreed; blocked on the
  output format (PDF / PNG / HTML) and on the repository URL and contact to
  put in the footer.

## Open

Ordered by value, not by effort.

- **Finish testing the GUI layer.** The floor is no longer zero:
  `app/tests/test_ui.py` covers the `JobTabMixin` protocol, the main window's
  ngspice wiring, the Settings round trip and the manual viewer, and simply
  constructing each tab carries most of its `__init__`. Coverage of `app/`
  went from **50% to 69%**, and no UI module sits below 59% (`main_window`
  82%, `manual_dialog` 97%, `circuits_tab` 77%). The target chosen, and
  worth keeping: **test what every tab shares and gets wrong the same way,
  not what each tab draws.** Layout and geometry are excluded on purpose —
  they change constantly and break tests without finding bugs. What is still
  thin is `sizing_tab` (the largest UI module by far) and the per-tab run
  paths, which need a real simulator and are the expensive half.
- **Decide whether the API key needs a keyring.** The cheap half has
  landed: `ANALOG_LLM_API_KEY` in the environment overrides the stored key,
  the Settings dialog shows it read-only and does not write it back, and both
  the dialog and the manual now say plainly that the saved key is plain text
  (registry on Windows, an ini file elsewhere). That gives the shared-machine
  case an answer without a dependency. What is still open is the general one:
  a `keyring` dependency would protect the key for users who do not know to
  set an environment variable, at the cost of a platform-specific package
  that has to survive three freezing toolchains on two platforms. Worth doing
  only if this app is expected to run where its users do not control the
  machine; write down the answer either way.
- **Connect a knowledge base to Project Cairn.** Cairn was initialized with
  the graduation provider deferred (`provider: none` in `.cairn/config.yaml`),
  which is fine — LOG, topic notes and audit all work without one. Graduation
  is the cross-project half, and it stays unavailable until an Obsidian /
  Notion / Lark target is configured at the first graduation.

## Ideas, not commitments

No one has committed to these; they are recorded so the thought is not lost.

- More AnalogGym circuits. Two upstream circuits are deliberately unregistered
  (`Qu_LEC` ships an empty netlist; `Tan_CLIA`'s default widths fall below the
  SKY130 model-bin range) — that exclusion is intentional, not a gap.
- Sizing contracts beyond the amplifier one. Importing a custom design
  currently requires `.subckt <name> gnda vdda vinn vinp vout`; LDOs and other
  topologies have no import path.
- macOS packaging. The test matrix runs on macOS, but no macOS build job
  exists — only Windows and Linux artifacts are produced.

## Decided against

Reopening these is fine, but start from the reasoning, not from zero.

- **Re-capturing the other eight manual screenshots.** Only the Sizing one
  was replaced for v1.4. The tabs behind the rest have not changed materially
  since those images were taken, and re-capturing them through offscreen Qt
  produced emptier screenshots than the ones already committed.
- **Filling in every missing docstring.** Coverage of public definitions was
  raised from 45% to 56% by documenting the two files that define the
  concurrency contract (`SimWorker`, `JobTabMixin`) plus the registry
  dataclasses. The six tabs' `on_job_finished` / `on_job_failed` overrides are
  intentionally left bare — the protocol is stated once, in the mixin.
- **Fixing `analoggym/README.md`'s stale path.** It points the Sizing tab at
  `app/core/sizing.py`, which became a package in v1.4. Correcting one word
  costs less than this entry — but a snapshot edited for local convenience
  stops being a snapshot, and dated analyses in this repository cite these
  files as fetched. The discrepancy is noted in both READMEs instead, where
  a reader of *this* project will actually meet it.
- **Editing the vendored trees.** `analoggym/`, `circuit-skills/`, `gmoverid/`,
  `ngspice/` and `transistor-models/` are upstream snapshots that the app reads
  as shipped and that dated analyses in this repository cite. Behaviour changes
  are adapted around in `app/`.
- **Weakening the source-leak gate** in `linux-nuitka` to make a build pass.
  That gate — no `app/` `.py` or `.pyc` anywhere in the distribution — is the
  entire reason the Nuitka route exists alongside PyInstaller.
