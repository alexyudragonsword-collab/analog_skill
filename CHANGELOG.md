# Changelog — Analog Studio

All notable changes to the desktop app (`app/`). Versions before 1.0 were
development milestones on the `claude/gmoverid-skill-analysis-7ron1c` branch;
vendored skill trees (`ngspice/`, `gmoverid/`, `transistor-models/`,
`circuit-skills/`, `analoggym/`) are archived as-is and never modified.

## v1.4 — unreleased  (version bumped 2026-07-15)

Design import + netlist viewer in the Sizing tab.

- **Documentation overhaul**.  `README.md` / `README.zh-CN.md` now lead with
  Analog Studio instead of introducing the repository as three Claude
  skills (the app had one block quote); their badges pointed at the
  *upstream* repository, so a visitor saw someone else's stars and issues.
  The skills are kept in full as collapsible sections.  `APP_README.md`
  documented one build path when CI produces five — it now has the whole
  table, local build commands and the workspace-vs-user-data split.  New
  `CONTRIBUTING.md` (the two checks CI runs, why test suites must not run
  concurrently, regenerating the netlist-derived schematics, what each CI
  job guards, how to release) and `CLAUDE.md` (project guidance for Claude
  Code, previously git-ignored alongside local settings).  The Sizing
  screenshot was re-captured on v1.4 after a real 80-evaluation run: the
  old one predated `Runs…`, `Waves…`, `Import ▾`, `Netlist…` and the AI
  buttons, and showed no run at all.  Public docstring coverage went from
  45% to 56%, concentrated where it pays: `SimWorker` and `JobTabMixin` now
  state the concurrency contract (one thread because the skills' scratch
  paths are fixed; render closures run on the GUI thread) that the six
  tabs' handler overrides implement.
- **`app/core/sizing.py` split into a layered package**.  The module had
  grown to 1638 lines carrying eight unrelated responsibilities; it is now
  `app/core/sizing/` with one module per responsibility and a strictly
  one-directional dependency graph (`spec → registry → assets → scoring →
  evaluation → user_circuits → report → optimizer → runs → plots`).
  `SizingRun` moved out of the plain-data layer, together with
  `change_summary`, into a new `report` module — its `report()` reaches
  into the registry, the scorer and the evaluator, so it is presentation
  over those layers, not data.  Behaviour is unchanged: `__init__.py`
  re-exports the same public names, so `from app.core import sizing` and
  every `sizing.x` call site are untouched, and all 70 top-level
  definitions were moved byte-for-byte (verified by comparing the AST of
  every definition before and after).
- **CI: lint gate + cross-platform test matrix**.  A new `lint` job runs
  `ruff check` over `app/` and `tools/` against a checked-in `ruff.toml`
  (defect rules — pyflakes/bugbear/pyupgrade/pycodestyle — with the
  vendored skill trees excluded and the codebase's deliberate style
  choices ignored, each with its reason).  The 34 findings it surfaced are
  fixed in this release: dead imports and locals, `Callable` imported from
  `typing` instead of `collections.abc`, three `raise` sites inside
  `except` that dropped the original exception (`from exc`), six `zip()`
  calls now explicit about whether unequal lengths are a bug
  (`strict=True`) or intended (`strict=False`).  The `pytest` job became a
  3-OS matrix (Ubuntu / Windows / macOS) so path and Qt-construction bugs
  are caught on the platforms the app is actually shipped for; ngspice is
  installed where available and the simulation tests self-skip elsewhere.
- **Dependencies now have upper bounds** (`numpy<3`, `matplotlib<4`,
  `scipy<2`, `PySide6<7`, and the dev tools likewise) — an unbounded
  requirement lets a breaking major release reach a frozen build without
  ever failing CI.
- **Fixed — user data survived neither an upgrade nor a hostile netlist**:
  - Saved runs (`sizing_runs/`) and imported circuits (`user_circuits/`)
    were stored inside the per-version workspace, which `paths.
    _prune_old_workspaces()` deletes on the first launch of a new version
    — every saved run and custom circuit was lost on upgrade, contrary to
    the documented "persistent across sessions".  They now live in a
    version-independent user-data store next to the SKY130 PDK
    (`paths.user_data_dir()`, exported as `ANALOG_USER_DATA_DIR`), and
    `paths._migrate_user_data()` moves data left in older workspaces into
    it before pruning, so upgrading from ≤1.3 keeps everything.
  - The `.subckt` name in an imported netlist was matched with `\S+` and
    used directly as a filename, so a crafted netlist declaring
    `.subckt ../../../evil …` could write outside the workspace.  The name
    is now restricted to a SPICE identifier and re-checked before it is
    joined to a path.
- **Protected Linux build (Nuitka)**: a new `linux-nuitka` CI job compiles
  the self-written `app/` to native machine code — the distributed package
  contains no `app/` `.py`/`.pyc`, so the application source cannot be
  recovered from the install directory (the PyInstaller packages ship
  `app/` as decompilable bytecode).  Both Nuitka builds now force full
  `app/` compilation (`--include-package=app`); the Linux job fails if any
  `app/` source leaks into the dist.  Vendored skill trees remain
  non-Python data that ngspice reads from disk — see `CODE_PROTECTION.md`
  for exactly what this does and does not protect.
- **Single-file Windows build (Nuitka `--onefile`)**: a new `nuitka-onefile`
  CI job produces one self-extracting `AnalogStudio.exe`.  The skill `.py`
  trees ride inside it as `skill_assets.zip` and are unpacked into the
  workspace on first launch (`app/paths.py::ensure_skill_assets`, mirroring
  the SKY130 PDK zip).  The standalone directory builds are kept alongside
  it — the single file is more convenient to hand out, but self-extracts
  its whole payload to a temp dir on every launch, so it cold-starts slower
  than the standalone build.

- **Import ▾ → Sizing values (.PARAM)…**: load a previously exported (or
  hand-edited) `.PARAM` file back into the variables table's init column
  — the counterpart of *Export best .PARAM…*; unmatched names are
  reported, expression-valued entries skipped.
- **Import ▾ → Custom circuit (netlist + .PARAM)…**: import your own
  SKY130 amplifier design as a new optimizable circuit.  The netlist
  must follow the AnalogGym amplifier contract
  (`.subckt <name> gnda vdda vinn vinp vout`, self-biased) and come with
  its `.PARAM` design-variables file.  The design is copied into the
  writable user-data store (`user_circuits/`), registered in the circuit
  drop-down, validated with one real evaluation on import (a netlist
  that produces no metrics is rejected and removed), persists across
  sessions, and gets the full pipeline: the 9-metric report, parallel
  evaluation, Waves… comparison, device-change summary and the AI
  features.  Only the amplifier contract is supported in this version.
- **Netlist…**: a viewer dialog showing the current circuit's design
  files — the DUT netlist, the design variables (rendered with the
  table's current init values) and the fully rendered testbench
  (absolute includes, DUT substituted); circuit-skills circuits show
  their `.cir.tmpl` templates instead.  For imported circuits the
  dialog also offers *Remove this imported circuit*.
- **Redrawn Sizing schematics**: all 20 AnalogGym circuit schematics
  (15 amplifiers + 5 LDOs) are redrawn with schemdraw, device-by-device
  from the netlists (`tools/gen_sizing_schematics.py`, with a
  programmatic completeness check against each netlist).  They replace
  the low-res vendored screenshots in the GUI, and the Alfio amplifier
  and the five LDOs — which shipped no schematic at all — now have one.
  The vendored AnalogGym tree stays untouched.

## v1.3 — 2026-07-15

Before/after characterization for sizing results.

- **Waves… (before vs after) — all 27 circuits**: a new button
  re-characterizes the *default* and the *optimized* sizing with the swept
  curves captured and overlays them, with panels per circuit family:
  - *amps* (15 AnalogGym + studio CM-OTA): differential gain and phase vs
    frequency, PSRR± vs frequency, Vout vs temperature (`wrdata` injected
    after each testbench analysis);
  - *LDOs* (basic + 4 variants): loop gain and phase at max/min load,
    PSRR, and the Vout-vs-VDD line-regulation sweep — the AC vectors are
    harvested from each testbench's own `plot` line (node names differ
    per circuit), the DC sweep reuses the TB's `_Vdrop` file (injected
    for ldo_basic, which lacks one);
  - *circuit-skills*: the simulate_* modules already return the arrays,
    so no netlist changes — 5T OTA / two-stage op amp get gain+phase
    Bode, the skill LDO gets loop gain/phase + PSRR + Zout, the StrongArm
    comparator (both entries) gets the latch and output transients with
    τ annotated, and the bootstrapped switch gets Ron-vs-Vin plus a
    switch-type comparison.
  Two extra evaluations (seconds for skill circuits, ~10-20 s for
  amps/LDOs); also works on runs loaded from **Runs…**.  Captures
  cross-check themselves against the `.meas` values (first AC point ==
  DC gain).
- **Device-change summary in every report**: the run report now includes a
  `device changes vs default` section — AnalogGym variables are grouped
  per device (`MOSFET_9_2  gm1_PMOS  W 1->5.89  L 1.5->1.52  M 14`),
  ordered by how much each device changed, with capacitors/bias currents
  as flat lines and unchanged variables collapsed into a count.  Applies
  to all 27 circuits (skill circuits fall back to flat per-variable
  lines) and reaches the GUI report box, **Runs… → Load**, and the AI
  explain prompt automatically.

## v1.2 — 2026-07-11

AI-assisted design (optional, bring-your-own LLM API) + a new sizing circuit.

- **New sizing circuit — current-mirror OTA** (`studio_circuits/`, the 27th
  Sizing entry).  Every other open, device-accurate, licensed circuit source
  is already wired in (AnalogGym's 20 SKY130 circuits + circuit-skills' 6 PTM
  entries); the remaining open LLM-benchmark repos (AnalogCoder, Analogagent)
  ship only level-1 ideal MOSFET models — and AnalogCoder has no license —
  so they don't fit the real-PDK pipeline.  This entry is therefore an
  *original* single-stage PMOS-input symmetric OTA authored on the open SKY130
  PDK, not vendored: it reuses the AnalogGym `.subckt gnda vdda vinn vinp vout`
  contract + shared `TB_Amplifier_ACDC` harness, so it inherits the full
  9-metric report (DC gain / GBW / phase margin / PSRR± / CMRR / power /
  offset / temp-coeff) and the parallel evaluator.  Self-biased from one
  internal reference current, it converges robustly across the whole sizing
  box; default ≈ 42 dB / 0.37 MHz / PM 90° / 0.42 mW, with a genuine
  gain ↔ GBW ↔ power trade-off on its 500 pF load.
- **LLM-guided sizing algorithm**: a fourth `optimize()` algorithm where
  the configured LLM reads the circuit netlist / parameter semantics,
  bounds and targets, proposes candidate sizings round by round, and
  every candidate is measured by a real ngspice run whose cost is fed
  back — full closed-loop verification by construction.  Budget, cancel,
  parallel evaluation, best-point verification (`verify_key`) and run
  auto-save all work exactly as with the other algorithms; an
  unparseable reply falls back to Sobol sampling for that round.
- **AI advise…**: pre-run suggestions for per-variable init/bounds and
  budget, applied to the tables on confirmation.
- **AI explain**: one-click English design critique of a finished run's
  report, appended below the report.
- **Fix: Circuits tab circuits failed on Windows installs with a space in
  the path.** The 5T OTA / two-stage op amp / LDO / StrongArm comparator
  loaded their PTM model from the read-only install directory, and
  ngspice's *unquoted* `.include` truncates a path at the first space
  (e.g. a zip re-extracted to `…-pyinstaller (1)\`), so the model was
  "not found" and every one of them failed — only the bootstrapped
  switch worked, because it already repointed its model to the
  space-free workspace copy. All skill circuits (Circuits tab and the
  Sizing tab) now repoint to `NGSPICE_ASSETS/models` before simulating.
- **Smaller bundles**: the frozen builds no longer ship optuna and its
  dependency tree (SQLAlchemy, greenlet, alembic, …) — it is a
  source-only optional and the GUI hides the TPE option when absent.
  On Linux the unused Qt GTK3 platform-theme + EglFS plugins and the
  whole GTK widget stack are pruned, and ELF symbols are stripped
  (~47 MB off the Linux package; ~8–10 MB off Windows).
- **Dual-protocol client** (`app/core/llm_client.py`, stdlib-only):
  OpenAI-compatible (OpenAI / DeepSeek / Qwen / local Ollama …) and
  Anthropic (Claude); configured under Settings → LLM with a Test
  button.  API keys stay in local QSettings; leaving the model empty
  disables all AI features.  Offline test suite fakes the single HTTP
  chokepoint.

## v1.1 — 2026-07-10

Sizing run management + release pipeline.

- **Run management** in the Sizing tab: every completed optimization is
  auto-saved as JSON into the workspace (`sizing_runs/`). The new
  **Runs…** dialog lists saved runs and offers **Load** (restore report +
  convergence curve), **Compare** (overlay the convergence curves of
  several runs), **Use best as init** (warm-start the variables table
  from a run's best sizing) and **Delete**.
- **Linux package**: the CI now also builds a PyInstaller onedir tarball
  on ubuntu (`AnalogStudio-linux-pyinstaller.tar.gz`) from the same
  cross-platform spec; the vendored linux64 `bsimcmg.osdi` means FinFET
  works out of the box.
- **GitHub Releases**: tag builds automatically publish a Release with
  all three packages attached and the matching CHANGELOG section as the
  notes.

## v1.0 — 2026-07-10

Sizing P4 + release polish.

- **Parallel evaluation** in the Sizing tab: a *Parallel evals* spinner
  (default min(4, CPU cores)) dispatches concurrent ngspice runs into
  per-slot work directories. `set num_threads=1` is injected into each
  testbench when running concurrently — ngspice's internal threading
  spin-waits under concurrency, and pinning it yields a measured **3.5×
  wall-clock speed-up on 4 cores** (16-eval DE run: 72 s → 20 s).
  circuit-skills circuits stay serial (import isolation) and the spinner
  disables automatically.
- **Differential evolution** algorithm (scipy, global search for large
  budgets) alongside Sobol+Powell; Optuna TPE now asks/tells in parallel
  batches too. Budget remains a hard dispatch cap and Cancel keeps the
  best-so-far under every algorithm.
- **StrongArm comparator fast τ-proxy** sizing entry (~1 s/eval: latch time
  constant τ from the wave testbench + a total-width power proxy). After
  the run the best point is automatically re-measured with one full
  3×1000-cycle probit evaluation; the report shows the verified σ / power
  / decision time next to the proxy metrics. The full ~2 min/eval entry
  remains available.
- **Bootstrapped switch is now optimizable**: scalar Ron metrics
  (`ron_bts_max`, max/min flatness) post-processed from its gds-based Ron
  testbench, with the sampling-switch width `W.sw` and clock frequency as
  variables (~0.5 s/eval). The Circuits-tab Ron report also prints the
  NMOS/CMOS/bootstrapped max-Ron and flatness numbers.
- **FinFET availability probe deepened**: an end-to-end BSIM-CMG
  micro-simulation (cached) now backs `finfet_available()`, so ngspice
  builds whose OSDI loads but cannot actually run the model (e.g. the
  KLU-solver ngspice-42 on some CI runner images) grey out FinFET instead
  of failing at run time.

## v0.12 — 2026-07-09 (Sizing P3)

- The four Circuits-tab circuit-skills circuits (5T OTA, two-stage Miller
  op amp, LDO, StrongArm comparator) plug into the same
  evaluate→score→optimize pipeline on their PTM models, via their
  plot-free `simulate_*()` metric paths inside the existing import
  isolation. Best sizings export as `name = value` text and can be fed
  back into the Circuits tab.

## v0.11 — 2026-07-09 (Sizing P2)

- Full AnalogGym registry: 20 SKY130 circuits (15 literature amps + Basic
  LDO + 4 LDO variants), each validated on ngspice-42; two defective
  upstream circuits excluded (Qu_LEC empty netlist, Tan_CLIA width below
  the SKY130 model bins).
- Editable metric targets with **hard constraints** (10× violation
  weight); per-metric ✓/✗ report.
- Optional **Optuna TPE** algorithm (dev dependency); manual section 5b
  with screenshot.

## v0.10 — 2026-07-09 (Sizing P1)

- New **Sizing tab**: vendored the AnalogGym (ICCAD'24, BSD-3) open subset
  (`analoggym/`), SKY130 PDK auto-extracted to the workspace on first use;
  evaluate→score→optimize core (`app/core/sizing.py`) with the built-in
  Sobol+Powell optimizer, live progress, cancel, convergence plot and
  `.PARAM` export.

## v0.9 — 2026-07-08

- Hand-drawn-quality **schemdraw schematics** for the five Circuits-tab
  circuits, pre-rendered at build time and shown as soon as a circuit is
  selected.
- Circuits tab P2+P3: comparator amplitude/common-mode/tail/latch sweeps,
  LDO compensation sweeps and theory cross-checks, comparator self-check
  with quantitative assertions, op-amp pole/zero table.
- Archived `circuit-skills/` (five block-level circuit skills) with
  analysis + GUI-integration assessment; later joined by
  `ANALOG_REPOS_ANALYSIS.md` (AnalogCoder / Analogagent / AnalogGym
  comparison).

## v0.8 — 2026-07-08

- **FinFET support** (PTM-MG 7–20 nm HP/LSTP, 20 devices): BSIM-CMG loaded
  at run time through ngspice's OSDI interface with a vendored
  `bsimcmg.osdi` (linux64 + win64, compiled by CI with OpenVAF); NFIN
  sizing semantics, real device capacitances, designer/browser/comparison
  integration. FinFET entries grey out when the user's ngspice lacks OSDI.
- GUI fits small / HiDPI screens (scrollable control columns, adaptive
  window size).

## v0.7 — 2026-07-07

- Project review sweep: gm/ID table invalidation on parameter change,
  atomic workspace sync, clean worker shutdown, matplotlib thread policy;
  test CI on ubuntu (`test.yml`); packaging trim (Qt module excludes);
  JobTabMixin refactor; MIT LICENSE + PTM NOTICE.
- Fixed frozen builds missing `scipy.signal`; fixed the Nuitka Windows
  build (Qt plugins, delvewheel DLLs, Nuitka 2.x pin).

## v0.6 — 2026-07-06

- All remaining skill features exposed in the GUI: 20 PTM bulk models
  (180 nm – 22 nm), comparison tab, validate/lookup tools, full ngspice
  example parameter surface (Advanced groups).

## v0.5 — 2026-07-05

- Initial public milestone: PySide6 app with gm/ID Designer, ngspice
  Examples, Curve Browser tabs; serial simulation worker + log panel;
  bilingual (zh/en) illustrated manual (F1) and About dialog; PyInstaller
  + Nuitka Windows packaging via GitHub Actions.
