# Changelog — Analog Studio

All notable changes to the desktop app (`app/`). Versions before 1.0 were
development milestones on the `claude/gmoverid-skill-analysis-7ron1c` branch;
vendored skill trees (`ngspice/`, `gmoverid/`, `transistor-models/`,
`circuit-skills/`, `analoggym/`) are archived as-is and never modified.

## v1.2 — 2026-07-11

AI-assisted design (optional, bring-your-own LLM API).

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
- **AI explain**: one-click Chinese design critique of a finished run's
  report, appended below the report.
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
