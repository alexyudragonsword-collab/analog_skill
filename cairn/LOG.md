# Project Cairn Log

This file records substantive progress in reverse-chronological order — newest entry at the top, right below this line. Keep each entry short — summary and pointer only; conclusions settle into `cairn/<topic>.md`.

## 2026-09-24 · The restart apart from the finish: shipped in plain CMA-ES

- Maintainer said do it. Two control arms on the sixteen open rows:
  restart-only (finish arm, no model call) and the finish at an
  eight-generation stall window, plus restart-only at that window for
  the full square (48 runs). Restart alone: 9/16 feasible, sum 5.64 —
  the finish arm's nine rows, no model. Finish at 8 gen: 9/16, sum
  4.53 (was 5.53). Restart at 8 gen: 7/16. Shipped: plain `cmaes`
  restarts from its best point on a 60-evaluation stall
  (`run_cmaes_restart`); ahead of the finish the window is at least
  `STALL_GENERATIONS` (8) generations (`_stall_window`). Tests extended
  (restart note, zero-cost early stop, 128-evaluation hand-off on four
  workers). Correction note on yesterday's "half of it is the
  restart"; new table and reading in `cairn/pitfalls.md`; CHANGELOG
  vNext, README, ROADMAP items rewritten (window, IPOP).

## 2026-09-23 · Finish at three seeds: 20 of 27 feasible against 18

- The finish tier landed: nine circuits × seeds 0–2, `cmaes_llm_finish`
  against `cmaes` at the same budget and population, amplifiers and
  LDO rerun at population 16 / the fixed LDO reader (42 runs). CMA-ES
  alone leaves 9 of 27 rows open; the finish arm improves 7, closes 2,
  loses 2 (both amp_leung_nmcf); feasible 20 vs 18, cost sum 5.53 vs
  7.99. The notes show half the win is the restart from the finished
  point, not the model call (amp_ramos_pfc s0: finish found nothing,
  restart 1.03 → 0.49), and the stall rule fires at 80–256 evaluations
  at population 16 — under four generations. Table and reading in
  `cairn/pitfalls.md`; ROADMAP: generation-based stall window; README
  carries 20/27 and 23/24. Docs only, no code.

## 2026-09-23 · Warm start at three seeds: 23 of 24

- Maintainer asked for three runs per cell on the finish and the warm
  start. Warm start done, all seeds through the shipped path: 23/24
  rows beat cold CMA-ES at 200 with archive best + 100; archive
  lookup alone 17/24; model proposals beat the archive 5/24. Table in
  `cairn/pitfalls.md`. The finish tier (five amplifiers × three seeds
  × two arms at the current population, plus seed 2 on the other
  four circuits, 38 runs) is running; recorded when it lands.

## 2026-09-23 · Failure gate in CMA-ES: built, measured, off by default

- Maintainer picked the review's third item. `models.failure_gate`
  trains the archive's failure classifier on demand; `run_cmaes`
  redraws points under 30 % p_ok up to three times, refits every ten
  generations, counts redraws in the notes. Test: an archived dead
  region, fewer evaluations land in it. A/B on ldo_basic, four seeds
  from an empty archive: failed evaluations 60 vs 72 but endpoint
  worse on three of four (means 0.76 vs 0.54); from a 1024-point
  archive one seed 1.05 → 0.34. Ships off; table and the edge-of-
  feasibility reading in `cairn/pitfalls.md`; ROADMAP: characterised
  case at several seeds, lower threshold.

## 2026-09-22 · Sensitivity-informed finish built, measured negative, shipped off

- Maintainer picked the review's first-ranked item: local linear fit
  on the archive around the best point → sensitivity lines in the
  finish prompt + scan centred on the predicted amount. Built
  (`sizing/sensitivity.py`, `FINISH_SENSITIVITY`, tests on a synthetic
  cloud and the one-variable finish harness). A/B on three real CMA-ES
  endpoints, two runs per arm: no case better than the plain finish,
  amp_ramos_pfc worse in all four runs, both scan variants. Ships off
  by default with the seam and notes kept; table and reading in
  `cairn/pitfalls.md`; ROADMAP: separate prompt lines from scan, more
  seeds, before any retry. Gate 215 green.

## 2026-09-22 · CMA-ES population rounded to whole waves of workers

- Maintainer picked the ROADMAP lever. `_popsize` rounds pycma's
  4 + 3 ln n up to a multiple of `workers` (13 → 16 on four; restarts
  double to a multiple too); both CMA-ES runners use it. Test on the
  amp-kind bowl. Measured on the four affected amplifiers: 600
  evaluations in 10–20 % less wall clock, equal-wave budget (740)
  changes nothing, results 1–1–2 (CMA-ES) and 2–0–2 (surrogate) on
  one seed. Kept as default; table in `cairn/pitfalls.md`; ROADMAP
  item closed; CHANGELOG vNext opened.

## 2026-09-22 · v1.7 build green and release published

- Released v1.7 (version bump, CHANGELOG section dated with its lead
  paragraph, workflow dispatched with the release tag). Build run 109
  green on all six jobs including the source-leak gate; Release
  published 2026-09-22 04:34 UTC with five packages (Windows
  PyInstaller / Nuitka / onefile exe, Linux PyInstaller / Nuitka),
  scikit-learn inside the frozen builds. Contents: the v1.6
  Optimize-button fix, the LDO variants' mapping, archive + warm
  start, metric models, Try next's warm start, the lq-CMA-ES pilot.

## 2026-09-21 · Try next offers the warm start

- `runs.next_step(known=)` takes the archive's best under the current
  targets; when it beats the run's result the action is 'warm' (same
  seed and budget, start from the point), placed after the finish rule
  and before the seed rule. The tab passes `_known` (refreshed before
  the step is computed) and Try next checks the box. UI tests now run
  with the archive patched out by default: earlier ngspice tests fill
  the real archive and changed the suggested step. ROADMAP item closed.

## 2026-09-21 · Second seed through the shipped path; model fit defect fixed

- Running the shipped `model_propose` on the imported LDO archive
  predicted 31 for the archive's best row (true 0.93): regulation
  metrics fitted raw, garbage rows from failed simulations set the
  scale. Fix: 'absmin' and decade-spanning metrics fitted as log |y|,
  targets winsorised at 1/99 %; rank correlation true vs predicted
  cost 0.996–0.999 on the archives; regression test at a known point
  with garbage rows. Gate 212 green.
- Seed 1, eight target sets: archive + warm start 100 beats cold
  CMA-ES 200 on 7 of 8 (14 of 16 over both seeds); model proposals
  beat the archive on 1 of 8 (3 of 16). Table in `cairn/pitfalls.md`.
  ROADMAP: wire the archive warm start into "Try next"; proposals stay
  a menu entry.

## 2026-09-21 · GUI end to end: flow works, Optimize button was dead in v1.6

- Drove the real Sizing tab offscreen: characterise 400 → new target
  → model proposals → warm CMA-ES 100 (0.015) vs cold 100 (0.189) on
  studio_cm_ota. First click crashed: `clicked(bool)` passed `checked`
  as `resume` since the continue-runs commit, inside v1.6 — the
  Optimize button has raised and started nothing since the release.
  Fixed (lambda + isinstance guard), the seed UI test presses the real
  button. CHANGELOG says so; whether to cut v1.6.1 is the maintainer's
  call. Second seed on the eight target sets running through the
  shipped path (scratchpad `seed1`).

## 2026-09-21 · Metric models shipped (step 3)

- Maintainer said start the metric models. New `models` module (after
  `archive` in the import order): per-metric HistGradientBoosting +
  failure classifier trained on the archive on demand (cached, never
  pickled), `propose()` runs CMA-ES on the models from the archive's
  best under the targets and returns k distinct candidates. Two new
  `optimize` algos: `sobol` (characterise the whole box into the
  archive) and `model_propose` (verify k proposals in one batch, best
  verified = result). Menu entries in the Sizing tab; scikit-learn in
  requirements, app.spec and the three Nuitka jobs — build run 104
  on the push went green on all six jobs, so the frozen builds carry
  scikit-learn; Tests run 129 green. Tests on the bowl: the models
  propose within 4 of (30, 100 MHz) from a 256-point sample; gate 212
  green. ROADMAP: GUI end-to-end run, frozen build, second seed.

## 2026-09-21 · Archive and warm start shipped (steps 1 and 2)

- Maintainer said do 1 and 2 first. New `archive` module (between
  evaluation and user_circuits in the import order): every evaluation
  appended as a JSON line per circuit, `best(circuit, names, overrides)`
  re-scores under the current targets. `optimize(start=)` takes a known
  point; CMA-ES and the surrogate inject it and step at σ 0.1. Sizing
  tab: archive count and best-under-these-targets label, refreshed on
  circuit and target edits, checkbox "Start from the best known point".
  Three tests (archive, warm start on the bowl for three algorithms,
  UI plumbing); gate 209 green. Step 3 (metric models) stays on ROADMAP.

## 2026-09-21 · Amortised surrogate measured: 7 of 8 target sets, archive is half of it

- Asked whether pretraining once per circuit and reusing on new targets
  pays. Sampled amp_hoilee (2048, 36 min) and ldo_basic (1024, 15 min),
  learning curves (GBT beats GP from 512 on; hard metrics gain ~0.1 R²
  per doubling), then four target sets per circuit: pretrained assets
  + 100 real evaluations beat cold CMA-ES @200 on 7 of 8, four to all
  met. Re-scoring the archive alone (no model) wins 6 of 8; the models
  add on 2. Found: `run_cmaes` never evaluates its start point and
  σ 0.25 walks off a warm start — σ 0.1 + inject reaches 0 where 0.25
  gave 0.40. Table and reading in `cairn/pitfalls.md`; ROADMAP: archive,
  warm start, characterise job. No code changed.

## 2026-09-20 · Batch-fill measured: wall clock fixed, benefit gone

- Filled lq-CMA-ES on the eight circuits: every parallel row now in
  CMA-ES's wall time (10.3 vs 10.9 min etc.), but the surrogate then
  evaluates 85–94 % of each population and lands between CMA-ES and the
  unfilled variant: 2–1 with five ties against CMA-ES by small margins,
  and the ldo_basic all-met result is lost (0.89). Not separable from
  CMA-ES at equal wall clock on one seed. Stays a pilot; default stays.
  Table and the population-shape lever (13 → 16 on four workers, for
  both algorithms) in `cairn/pitfalls.md`; ROADMAP updated. Two container
  restarts killed the run twice; the runner is resumable and the wait
  was done in the foreground.

## 2026-09-20 · cmaes_surrogate fills its workers

- Maintainer said do the batch-fill fix first. Each surrogate step's
  cumulative count is rounded to whole waves of `workers` (4, 8, 12 on
  four workers instead of pycma's 1, 2, 3, 5); skill circuits (serial)
  unchanged; run notes list the step sizes; test on an amp-kind bowl
  (skill circuits ignore `workers`). Gate 206 green. Measurement on the
  eight circuits running (scratchpad `plan-s2`) against this morning's
  CMA-ES and unfilled-surrogate rows.

## 2026-09-20 · GP pipeline evaluated: not worth building now

- Asked to evaluate a Gaussian-process pipeline as such. Two numbers
  added to the surrogate probe in pitfalls: CMA-ES + finish reaches 0
  on amp_hoilee by 200 evaluations where the local GP loop's 184
  reached 0.42; GP fit time 1.7 / 8.5 / 33 s at 100 / 200 / 400 points
  per metric (n³). Verdict in the reply: not before lq-CMA-ES's
  batch-fill fix is measured at equal wall clock; if ever, as a
  cost-only or smooth-metrics model, not the full per-metric pipeline.

## 2026-09-20 · lq-CMA-ES measured: 2–1 per evaluation, 2× wall clock

- Eight circuits at 600, seed 0: surrogate better on nmcf (0.85 vs
  1.28) and ldo_basic (0, all met, vs 1.05), worse on ramos (1.29 vs
  0.58), five ties at 0. Every parallel run took twice the wall time:
  the tau-check loop evaluates 1, 2, 3, 5 points at a time and idles
  three of four workers. Stays a pilot in the menu; default unchanged.
  Table and reading in `cairn/pitfalls.md`; ROADMAP has the batch-fill
  fix as the next step if it is to go further.

## 2026-09-20 · lq-CMA-ES pilot: `cmaes_surrogate`

- Maintainer said do it. Added `cmaes_surrogate` to `optimize()`: pycma's
  LQModel ranks each CMA-ES population, points are evaluated in the
  model's order until Kendall tau ≥ 0.85, the rest are ranked by the
  model; the loop is a port of `SurrogatePopulation.__call__` with each
  step batched across the workers, failed points kept out of the model.
  Menu entry in the Sizing tab, bowl test (fewer evaluations than plain
  CMA-ES to 1e-4, survives failing evaluations), CHANGELOG vNext.
- Measurement against `cmaes` at 600 on the eight-circuit protocol is
  running (scratchpad `plan-s`); the result decides whether it stays a
  pilot.

## 2026-09-20 · Surrogate-assisted optimisation: probed, not adopted

- Maintainer asked for a feasibility view of GP/NN surrogate → CMA-ES
  on the model → SPICE verification. Measured instead of argued:
  Sobol samples on amp_hoilee (whole box and ±10 % box) and ldo_basic,
  GP and gradient-boosting per metric, three surrogate-CMA-ES rounds
  verified in SPICE. Power/PM/GBW learnable; offset, tempco, settling,
  CMRR/PSRR not; whole-box optimum is fiction (predicted 0.02, real
  21); local refitted loop 3.71 → 0.42 in 24 verifications. Table and
  reading in `cairn/pitfalls.md`. Recommendation: pilot pycma's
  built-in lq-CMA-ES as one more algo before any GP pipeline.

## 2026-09-20 · The four LDO variants report their own numbers

- Fixed the variants' metric mapping without touching the decks: a
  per-circuit bench table (`LdoBench`) undoes each deck's typed-in
  `vout − 4·Vref` and `Power/1.8 − 5 mA`. Defaults now read +5 mV,
  −30 mV, +3 mV, −313 mV output error (folded cascode really is low)
  instead of −5 V. Half the earlier diagnosis corrected in pitfalls:
  the column order was right and the load-regulation numbers were
  real; the unit label (V/A for a 1/A quantity) was the lie.
- Titles and labels carry each circuit's real conditions; three tests
  (table vs decks, fold from a fabricated row, defaults near their own
  reference). ROADMAP item rewritten as the design question it now is:
  Basic_LDO's targets on decks whose LNR sweep starts in dropout.

## 2026-09-20 · Restarts never fire; v1.6

- Four CMA-ES runs at 1200: no IPOP restart triggered in any; budget
  alone took both `ldo_basic` seeds to all targets met. ROADMAP:
  drop the restart code or retrigger it on the history's stall.
- Released v1.6 (version bump, CHANGELOG section dated, workflow
  dispatched with the release tag). Build run 98 green, all six jobs
  including the source-leak gate, with `cma` in the frozen builds;
  Release published 2026-09-19 23:34 UTC.

## 2026-09-20 · The default on 26 circuits: 12 of 22 feasible, two bugs found

- Sweep done (about a day of simulator time). Feasible 12 of 22 under
  the ten-target spec; five stopped early at cost 0. Found: the output
  clearing deleted two LDO variants' decks (fixed, tested); the four
  LDO variants' metric mapping is wrong at the shipped defaults (−5 V
  output error) — registered since v1.4, never run before; recorded as
  a known defect, ROADMAP has the fix. All remaining phase-margin
  ceilings removed (LDO, circuit-skills) — `ldo_basic` becomes
  feasible; a ceiling nothing measures is a guess.
- Settling target 2 µs is tight on four amplifiers; ROADMAP asks the
  2-or-2.5 question with the table. IPOP restart runs still going.

## 2026-09-20 · Six asks: settling time, stall-triggered finish, skill audit

- Maintainer said do all six. Done in code so far: (2) the finish
  starts when the search stalls (`STALL_EVALS`), CMA-ES resumes from
  the finished point with what is left; (4) circuit-skills simulators
  parse fixed filenames — outputs cleared before each evaluation; (6)
  settling time. The step-response measurement decided (6): the 156°
  design never settles (29 µs, 23 mV short), 78–88° settle in ~0.9 µs,
  40° rings 31% — so `tsettle` (2 µs, 1% of a 100 mV follower step) is
  the tenth amplifier target and the 90° ceiling is gone. +0.1 s per
  evaluation. Amplifier cost values change from here.
- Next: (1) the 27-circuit sweep on the default, (5) IPOP restarts at
  1200 queued behind it, (3) release v1.6 after both.

## 2026-09-20 · LDO rows re-measured; the nine-circuit finish table

- On the fixed reader the phantoms were the good numbers (0.32, 0.36,
  0.24); DE + Powell honestly closes the LDO at seed 0 (Powell 9/18
  feasible); CMA-ES tallies stand (12/18, best or tied 16/18); the
  LDO's CMA-ES trajectories reproduce to the digit now — the
  discrepancy was the reader, closed.
- `cmaes_llm_finish` on nine circuits, two seeds: of six open rows it
  improves four, leaves one, ends worse than plain CMA-ES on one (LDO
  s0: the reserve was taken while the search was still improving).
  Default stands; ROADMAP asks for an adaptive reserve.
- Tables in `cairn/pitfalls.md`; CHANGELOG entries updated in place
  (unreleased).

## 2026-09-19 · The LDO phantom: failed runs inherited the last point

- The nine-circuit run of the three-proposal finish is in
  (`plan-f`), but while reading it two LDO endpoints with different
  sizings showed identical metrics. Cause: a failed ngspice run left
  the slot's previous wrdata files and the reader took them. Fixed in
  `evaluate()` / `capture_waves()` (`_clear_outputs`), regression
  test added. Every LDO number before this is suspect; amplifiers
  unaffected (metrics from the always-cleared log).
- LDO rows re-running on the fixed code (11 runs). The plan-f table
  is held until they land so it is written once, correctly.

## 2026-09-19 · Three proposals a round: 3 of 3 improved; stall rule off

- Same three CMA-ES endpoints, sonnet, three rounds: 1.03 → 0.89,
  0.45 → 0.25, 0.74 → 0.66 — the first finish variant to improve every
  case, best of five columns on two. 60–66 evaluations, 10–14 min.
- ramos's win came after a failed round: 3 of 6 now, largest gain of
  all. `FINISH_STOP_ON_STALL` default flipped to off; recorded as a
  correction beside the original. Test flipped with it.
- Container restarted once more mid-run; the resumable script lost
  nothing. Table in `cairn/pitfalls.md`.

## 2026-09-19 · The finish asks three times per round

- Maintainer said build it. `FINISH_PROPOSALS = 3`: parallel calls,
  one coarse scan across all directions, identical proposals collapse,
  best line refined; per-round reserve 30, total 90. `_line_search`
  takes a list of directions. Tests updated, one added (wrong / right /
  timid answers, the right one wins). Measurement on the three CMA-ES
  endpoints running, sonnet, three rounds forced, for the table next
  to the one-proposal runs.

## 2026-09-19 · Opus vs sonnet on the finish: not separable at n=1

- Same three CMA-ES endpoints, finish alone, three rounds forced.
  Opus 2 of 3 improved (4%, 22%), sonnet 1 of 3 (5%); sonnet's earlier
  stall-rule run had cut ramos 37% from the same point and its repeat
  found nothing — the model's own call-to-call spread exceeds any
  opus/sonnet difference. Opus faster per call. Table in pitfalls.
- Stall rule corrected: a round after a failed round improved 2 of 5
  times here (small); rule kept as a default, switch recorded.
- A container restart killed the sonnet run mid-way; the script now
  resumes from its result file. A queued runner also never started —
  its own `pgrep` matched itself; the third time this bit this session.

## 2026-09-19 · The CMA-ES finish on its three cases

- Maintainer asked for it. `amp_ramos_pfc` s1 0.4471 → 0.2836 (one
  round); `amp_leung_nmcf` s1 and `ldo_basic` s0 unchanged. One of
  three helped, none closed — the finish's usual shape. Default stands.
- LDO's CMA-ES trajectory did not reproduce between runs; amplifiers'
  did exactly. Recorded as a discrepancy, ROADMAP has the check.

## 2026-09-19 · CMA-ES is the default; portfolio removed

- Maintainer's three decisions, one commit: default `cmaes` (with the
  finish when a model is configured, DE without the package);
  `cmaes_llm_finish` added, `run_cmaes` takes a limit for it; `Try
  next` names the CMA-ES finish when it exists; `de_portfolio` removed
  with its constant, test and menu entry. CHANGELOG vNext carries a
  Removed bullet next to the earlier Added one rather than rewriting it.
- Open in ROADMAP: the CMA-ES finish is unmeasured; restarts untested.

## 2026-09-19 · Seed 1 and the 1200 tier agree: CMA-ES

- Full protocol in: 9 circuits x 2 seeds x 4 searches at 600, plus DE
  vs portfolio at 1200. CMA-ES feasible 12/18 (DE 6, Powell 8,
  constrained 7), best or tied 16/18, all 9 at seed 1; beats DE@1200
  on three amplifiers at 600. Restarts never fired — plain CMA-ES won.
  Portfolio loses 3 of 4 where it runs. Tables in `cairn/pitfalls.md`.
- Default not changed; ROADMAP carries the decision (CMA-ES default,
  `cmaes_llm_finish`, portfolio's future, restarts untested).

## 2026-09-18 · CMA-ES leads the seed-0 tier

- Nine circuits, 600 evaluations, seed 0: CMA-ES feasible on 6 (DE 3,
  constrained DE 4, Powell polish 3), best or tied on 7, and it solves
  the reference amplifier under the band at 600 where four DE-based
  runs could not. Loses to DE on `amp_ramos_pfc` and `ldo_basic`.
- Constrained DE's difference is SciPy's per-metric acceptance
  (Lampinen), not the objective: it refuses one-for-another trades —
  which wins `amp_hoilee_affc` and loses `skill_opamp2`. Corrected the
  earlier description in CHANGELOG and the docstring.
- Two runner lessons: SciPy batches constraints only with
  `vectorized=True` (first constrained run was 4x slower, pitfall
  recorded); the runner kept only the finish's notes, so CMA-ES's
  restart log for this tier is lost — fixed before the next tier.
- Running: DE vs portfolio at 1200, then all four at seed 1. Default
  unchanged until then. Table in `cairn/pitfalls.md`.

## 2026-09-18 · Four more searches, in the menu

- Maintainer asked which algorithms to try and then to build them all
  with GUI entries. Built: CMA-ES with IPOP restarts (`cma`, new runtime
  dependency, in `app.spec` hiddenimports and the three Nuitka jobs),
  DE + Powell polish, constrained DE (metrics as SciPy constraints,
  objective = capped margin sum via `scoring.slack`), DE portfolio (3
  seeds then continue the best; needs 12 generations of budget). All in
  `optimizer.py`, each writing its account to `notes`. Fake-objective
  tests on the 2-variable bootstrap circuit for three, a micro ngspice
  run for the constrained one.
- Not built: gm/ID-derived initial populations — needs per-circuit
  design equations the app does not have. Said so to the maintainer.
- Measurement on the eight-circuit protocol starts next; ROADMAP Open.

## 2026-09-18 · The measured order, in the GUI

- Maintainer asked how "seed, then budget, then finish" shows up in the
  app; proposed three layers, told to build them. Layers 1–2 in this
  commit: `sizing.next_step()` (finish if close, seed while < 3 tried,
  then 2x budget at the best seed) reading the saved runs; the status
  line names the misses via `scoring.feedback_line` (moved down from
  `llm_sizing` so tab and prompt share one sentence); *Try next* button;
  Seed box; run record carries algo/seed/budget/notes and the report
  prints the finish's account; defaults DE(+finish) and 600.
- Layer 3, next commit: DE's last population and costs on the run
  record (physical units), `optimize(resume=)` seeds from it and serves
  known points from a memo so the budget is all new evaluations; *Try
  next*'s budget step continues rather than restarts; *Continue* in the
  Runs dialog. `sizing.DE_ALGOS` names the algorithms this applies to.
- Pointers: CHANGELOG vNext (two entries at the top), ROADMAP Open
  (thresholds item replaces the seed-box item), tests in `test_sizing.py`
  (`next_step`, record fields) and `test_ui.py` (seed, Try next).

## 2026-09-18 · `amp_leung_nmcf` solved: seed 2, budget 1200

- Maintainer asked for it. DE at 552 was 2.06 (worst of three seeds),
  1.10 at 1152; the finish moved bias current and three lengths
  (1.10 → 0.036), then input-pair width and bias current (→ 0). All
  nine targets, PM 68°, 15 min. First feasible sizing on this circuit.
- Corrects "not a rescue when it stops far away" (`cairn/pitfalls.md`):
  cost distance was the wrong measure; whether the misses share a knob
  is the one that predicted this. Correction appended. ROADMAP's leung
  item closed as "seed and budget, not a mechanism".

## 2026-09-18 · Three open questions, answered as far as the night allowed

- Reference amplifier under the band: circuit, not seed. Seeds 0/1/2
  land in three basins (PM 151°, PM 25°, offset 271 µV), none feasible,
  best 0.86 at seed 2; the band as a hard constraint sends DE to gain
  54 dB. Table in `cairn/pitfalls.md`; ROADMAP keeps it open with the
  two remaining candidates.
- Second seed on all eight circuits: 16 runs, DE alone finishes 4, the
  finish closes 2 (`amp_fan_smc` s0, `ldo_basic` s1), improves 7, does
  nothing in 3. Seeds disagree on every unfinished circuit, both ways
  (`amp_peng_tcfc` 0.58 → 0 by seed alone). Under today's targets 9/16
  end feasible. Conclusion recorded: the seed is worth more than a
  finish round; ROADMAP asks for a seed spin box.
- Circuit-skills targets lowered (previous entry). No code tonight
  beyond `optimize(seed=)`; records only in this commit.

## 2026-09-17 · Three open questions, in progress

- Order chosen: seed parameter first (all three need other seeds; it was
  hardcoded thrice), then the reference amplifier under the band and the
  circuit-skills reachability in parallel, then seed 1 on every circuit.
- Circuit-skills answered: DE at 600 / 400 evaluations reaches 37.4 and
  65.7 dB against targets of 40 and 70; the boxes vary widths and bias
  only. Targets lowered to 36 and 64 (CHANGELOG vNext).
- `optimize(seed=)` added, 190 tests. Reference-amplifier seeds / hard
  ceiling and the seed-1 sweep are running; results in the next entry.

## 2026-09-17 · Phase margin is a band; the finish gets rounds

- Maintainer's three asks. (1) Phase margin 60–90: `MetricSpec.ceiling`,
  a `'max'` metric with one is penalised on both sides; every 60° spec
  carries `ceiling=90`, the CM OTA's ≥ 55 is left alone. The 156° design
  now costs 1.1. (2) The finish runs up to three diagnose-and-search
  rounds, each from the previous best, with earlier proposals and their
  outcome fed back and "do not repeat" — not more DE, which had
  converged and would hand back the same point. Points memoised across
  rounds; a line search that cannot beat its start stops refining.
  (3) Validation on eight circuits of four kinds, shipped path, real
  CLI: DE alone finishes 2, the finish closes 1 more (`amp_fan_smc`,
  three rounds each paying), improves 3, does nothing on 1
  (`amp_leung_nmcf`, PM 5°). The round after a failed round failed
  5/5 times, so the finish now stops on a failed round. Table in
  `cairn/pitfalls.md`.
- Then the reference amplifier under the band: DE lands in the 156°
  basin (cost 1.12), three rounds reach 151° — unsolved, and the one
  counterexample to the stopping rule (5/6 now; correction appended, rule
  kept). The ceiling removed a solution without supplying one; ROADMAP
  says what would tell seed from circuit.
- Pointers: CHANGELOG vNext (two new entries at the top), ROADMAP Open
  (ceiling question reframed), tests in `test_llm.py` (finish rounds)
  and `test_sizing.py` (band arithmetic).

## 2026-09-17 · `de_llm_finish` shipped; phase margin is a floor

- Both changes the maintainer approved, in one commit. Phase margin on
  every amp, LDO and circuit-skills spec is now `'max'` 60 (was `'target'`,
  met only at exact equality — so "all targets met" had been unreachable
  by definition). Cost values on those circuits moved; earlier tables are
  under the old rule and say so.
- New algorithm: DE to all but the last 16 evaluations, one model call
  asked *what* would fix the misses (told the app will search along it),
  a six-point scan at 0.25–2x the proposal plus three bisection rounds.
  Any provider; `state['cap']` in the optimizer is how the search leaves
  the finish its reserve. Five new tests, one on real ngspice.
- Live run of the shipped path, budget 616, real CLI: DE 0.0276 (only
  offset missed, 6%), model moved the three input-pair variables, scan
  hit **cost 0 at 1.5x — all nine targets met**, 606 evals, 10.5 min.
  First feasible sizing this project has produced — at PM 156°, which the
  floor permits and the equality rule would have charged 2.4 for. Bode
  checked: one crossing, dominant pole below 0.1 Hz, AFFC zero lifts the
  phase near crossover. Ceiling-or-not is an open ROADMAP question.
- Decided against, in ROADMAP: a model in the loop as the recommended
  search. `llm` / `llm_agent` stay. Open: measure the finish on other
  circuits; a second diagnosis round when two targets are short.
- Pointers: CHANGELOG vNext (both entries), `cairn/pitfalls.md` (two
  resolution notes appended), ROADMAP Open / Decided against.

## 2026-09-17 · The baseline nobody ran, and the last mile

- Ran LLM vs classical for the first time, all on `amp_hoilee_affc` at 60
  evaluations: sobol_powell 3.306, optuna 3.247, DE 1.205 (five seeds
  0.66–3.31, ~45 s each), LLM loop median 1.377 over ten runs (12–26 min).
  The LLM is the most *reliable* at that budget, not the best, and per
  minute DE wins outright.
- Feasibility: DE seed 3 reaches 0.5076 at 600 evals, 8/9 met, phase
  margin 39.7° short of 60. **At 1200 it is the same number** — the
  population had converged by ~530. Running DE longer is not a path.
- The last mile: from that DE point, six one-shot proposals (three with
  the operating point, three without) each moved 2–3 compensation
  variables, all in the right direction, all by the wrong amount. A
  seven-simulation bisection along each proposal's direction lands
  **3 of 6 at PM 59.8–60.2° with the other eight intact** (cost 0.004,
  21 s) — success exactly when the proposal touched the AFFC gm width.
  Operating point made no difference (2/3 vs 1/3). First near-feasible
  design this project has produced; ~11 min end to end.
- Found on the way: a `'target'` metric can never be reported met, since
  `met` demands violation ≤ 0 and that is equality. Cost 0 is unreachable
  by definition on every amp and LDO circuit. Not fixed — a spec decision.
- Facts in `cairn/pitfalls.md` (four new sections). Direction — DE search
  with an LLM-chosen line search as the finish — is the maintainer's call;
  ROADMAP and CHANGELOG untouched until then.

## 2026-09-16 · Operating points in the loop: measured, then turned off

- Ran it live as ROADMAP asked. Prompt plateaus ~83 kB at round 7, the extra
  ngspice costs 4.3 s and fires only on improvement (9 in 60 evals), cost
  3.3123 -> 1.2339 in 11.6 min — best of the session and, at 33% spread,
  meaningless as evidence.
- Two findings reversed the default. The seven out-of-saturation devices are
  identical across the whole design space, so they are topology, not a
  fault — **my declared metric could never have moved**. And in the loop
  targeting collapses to exactly 0.0 after four rounds once cost feedback
  arrives; cold it is 10-12x.
- `LOOP_OPERATING_POINTS = False`. Mechanism kept, capture unaffected.
- Corrections appended, not overwritten: `cairn/pitfalls.md` -> "Declare the
  metric before the run". The v1.5 CHANGELOG entry is published and stays;
  the correction lives in vNext.
- My own instrumentation bug ate the first run's third measurement (best
  point never recorded, silently zero samples). Re-run caught it.

## 2026-09-15 · Operating points: used, and aimed correctly

- The "reasoning or just caution" question is answered, and it is both —
  with targeting dominant. Shown the operating point the model moves the
  4 of 33 variables that size the offending devices 10-12x more than the
  rest; without it the ratio is ~1. It also moves less overall. Both
  p=0.029, zero overlap, n=4 vs 3 (a weekly limit ended the run).
- The design that made this measurable: a *countable* consequence of each
  hypothesis (caution -> smaller moves; reasoning -> skewed moves), chosen
  before the run. The outcome metric would have shown nothing again.
- Wired into `run_loop` on that basis — and on nothing else. The same
  proposals still failed to fix saturation; a loop is what fixes one-shot
  failures, which is the argument and the whole argument.
- **Live path unexercised** (same usage limit). Recorded in ROADMAP as the
  next step, because every earlier AI plumbing change here had a defect
  that only a live run surfaced.

## 2026-09-15 · v1.5 released; the Windows launch report is closed

- v1.5 published with all five packages. Tag pushes are refused by this
  session's credential proxy, so it went out through the workflow_dispatch
  route CONTRIBUTING documents for exactly that case (`release_tag` input —
  the workflow creates the tag itself).
- Shipped because two of the twenty-one entries reach every user and had
  nothing to do with the AI work: the half-extracted PDK (silent, on the
  default `workers` path) and `.include` file reads.
- "Double-click does nothing" reported resolved. **Root cause not
  recorded** — the three candidates were instrumented but which one it was
  never came back, so a recurrence starts from zero. Noted as such in
  ROADMAP rather than guessed at.
- A near-miss worth remembering: a script that reordered CHANGELOG bullets
  deleted 12 of 21 (117 lines). `git diff --stat` caught it. Prettier
  release notes are not worth a script that can eat them.

## 2026-09-14 · Operating points captured; measuring whether they are used

- `sizing.operating_points()` injects `op` + a targeted `show` into the
  rendered control block (existing seam, no vendored edit), parses the
  three-column output, joins it to the design variables via the netlist, and
  emits 3.1 kB of gm/ID, gm/gds and Vds-Vdsat, worst device first.
- Default amp_hoilee_affc: 7 of 30 devices out of saturation, six on one
  bias mirror. The nine metrics cannot express that.
- Result, n=5 per arm: the **declared** metric was null — both arms left
  seven devices in triode (p=0.09), despite being told exactly which and
  which variables size them. Cost, a secondary metric, separated cleanly
  (23/25 pairings, U=2, p=0.016; medians 8.15 vs 14.41). Reported in that
  order on purpose. A rival explanation stands: the prompt mentioning seven
  marginal devices may just induce caution.
- Both arms are far worse than the default sizing, so this ranks failure at
  a hard one-shot task, not success.
- Parser hazards: `cairn/pitfalls.md` -> "ngspice `show` is column-oriented".

## 2026-09-14 · Two gaps the llm/llm_agent comparison exposed

- Writing the comparison table turned up both: the agentic path never passed
  `--effort`, and Cancel could not reach an in-flight run.
- Cancel fixed properly — Popen plus a watcher that kills the process group
  (claude runs an MCP child of its own). 60 s child gone in ~3 s. Raises
  `CallCancelled`, not `LLMError`: nothing failed, and the tabs paint an
  LLMError red.
- Effort: my first reading, "an oversight, add 'low'", was wrong. The
  measurement behind `LOOP_EFFORT` is about 38 shallow turns costing an
  hour; the agent takes a handful that each digest the whole history. Kept
  at the provider default and named `AGENT_EFFORT` so it reads as a decision.
- Worth keeping as a habit: a comparison table is a cheap audit. Neither gap
  showed up while building either algorithm, only while putting them side by
  side.

## 2026-09-14 · Agentic algorithm: the model drives

- `llm_agent` added beside `llm`, on architectural grounds only — the model
  chooses what to simulate and when, instead of answering a fixed question
  per round. Explicitly not claimed to search better; the 33% spread
  measured earlier makes that unprovable either way.
- Shape: EvalService on loopback + a stdlib JSON-RPC MCP server forwarding
  to it, handed to the CLI via --mcp-config. Budget, Cancel, parallelism and
  scratch slots stay in the app, so the other four algorithms are untouched.
- First real run: 9 of 12 evaluations, 4.05 → 2.99, and a written account of
  why (input pair undersized; the AFFC cap beat the Miller cap for phase
  margin) — output the round-based loop cannot produce.
- Found on the way, and older than this work: `ensure_sky130()` could
  install a half-extracted PDK under `workers=4`. Details:
  `cairn/pitfalls.md` → "Check then create is a race".

## 2026-09-14 · The optimizer was telling the model a scalar

- Asked which of "more context" or "an MCP server" was worth doing. Neither
  as described: 0 of 20 netlists were being truncated, so the context half
  was empty. What the check turned up instead is that `_eval_one` computed
  all nine metrics, scored them, and returned only the number — the model
  proposing sizings never learned which target it missed.
- Feedback now names the worst misses with values, targets and percentages.
  `score()` became `sum(score_detail())` so the cost and its explanation
  cannot drift; `run_batch` grew `with_metrics` without changing what the
  other three algorithms receive.
- A/B came back **against** it: 1.4954 with the breakdown, 1.3798 without.
  But the earlier effort A/B's `low` arm is the same configuration as this
  one's `cost only` arm — 1.3182 vs 1.3798, **4.6% apart with nothing
  changed**. The effect is 1.9x that noise range, so one run per arm cannot
  resolve it. Replicated to n=3/n=4: the cost-only arm alone spans 33%, so
  the 4.6% floor was wrong by 7x — a two-run replicate samples spread, it
  does not measure it. Feature kept as a judgment call, labelled as not a
  measured win.
- Details: `cairn/pitfalls.md` → "A scalar is the weakest feedback channel
  you can give a model".

## 2026-09-14 · Effort is the latency lever; #2 and #3 were not

- Asked whether bigger prompts or an MCP server would cut the ~100 s round.
  Measured instead of reasoned: startup is 1.0 s of 101, so neither can —
  the cost is the model emitting ~11 k tokens, nine tenths of them
  reasoning. A smaller model is not it either (haiku 117 s > sonnet 101 s,
  more tokens to the same place).
- `chat(effort=...)` added on the same request-not-guarantee contract as
  `schema`. Loop asks for 'low' (25 s, 3 520 tokens, still 4/4 candidates);
  suggest_setup and explain_run keep the default, being read by a human.
- A/B came back (n=1 per arm, 60 evals): low 1.318 in 12.3 min, default
  1.280 in 26.0 min. Per evaluation the default is 3% better, which one run
  cannot separate from noise; per minute low is far ahead — the default was
  still at 1.534 when low had finished. Kept low, on the equal-time
  reading, and recorded that the curves differ in shape (low plateaus).
- Details and the full table: `cairn/pitfalls.md` → "A CLI agent is not a
  chat endpoint until you disarm it".

## 2026-09-14 · Structured output, and the latency it uncovered

- `chat(schema=...)` added as a request-not-guarantee: Claude Code enforces
  it with `--json-schema`, HTTP providers ignore it and keep parsing
  defensively, callers stay provider-agnostic. Schemas are built per circuit
  from its own variables — up to 56 names that a candidate previously had to
  restate verbatim or be dropped in silence.
- Verified live: 4/4 candidates, 0 missing keys, bare JSON with no fence.
- **The measurement mattered more than the feature.** A real round costs
  88 s with a schema and 112 s without — so the schema is free, and
  `chat()`'s 120 s default was about to make the LLM algorithm fall back to
  Sobol on every wide circuit. Floor raised to 300 s; the Sizing tab's time
  estimate, which counted only ngspice, was reading "2 min" for an hour.
- Corrected the "4-6 s per call" figure recorded yesterday — it was a toy
  prompt. Correction appended, not overwritten: `cairn/pitfalls.md` → "A CLI
  agent is not a chat endpoint until you disarm it".

## 2026-09-14 · AI features can run on a Claude subscription

- Third LLM provider: the locally installed Claude Code CLI, driven through
  `-p --output-format json`. Verified end to end before writing the UI —
  locate, configured, test_connection, a multi-turn JSON exchange, and
  `llm_sizing.suggest_setup` returning a real per-variable bounds dict.
- `chat()`'s contract is unchanged, so `llm_sizing` needed no edits: the
  history is flattened into the single prompt the CLI takes, which is what
  the HTTP providers are re-sent every call anyway. Stateless beat
  `--resume` for exactly that reason.
- The work was mostly *disarming* it, not calling it — tools off, user
  config excluded, empty cwd, fresh session id per call. Details and the
  measured numbers: `cairn/pitfalls.md` → "A CLI agent is not a chat
  endpoint until you disarm it".
- Scope decided by the maintainer: self-use, not published, so the usage-
  terms question raised in the feasibility review does not gate it.

## 2026-09-13 · ROADMAP's Open section is empty

- GUI tests extended from "does it build" to "what does it do with a reply".
  Three cross-tab rules now pinned: a failure re-enables the button, a
  raising render closure is reported not thrown, and gm/ID discards both a
  stale table and a dead one. Mutation-verified. 133 tests, coverage 71%.
- Two standing questions answered by the maintainer and recorded in
  *Decided against* rather than left open: no `keyring` (the env var covers
  the case that motivated it; the dependency must survive three freezing
  toolchains), and Cairn stays at `provider: none` (graduation earns its
  cost only when there is a second project to graduate into).
- English one-page overview delivered as an HTML artifact — the format
  decision that had blocked it.
- Open is now empty. Blocked-on-maintainer still holds one item that needs
  the reporting machine: does the single-file Windows exe launch there.

## 2026-09-11 · Cleared five ROADMAP items in one pass

- `.include` residual closed. Measuring it is what settled it: `.include` /
  `.inc` / `.lib` all pull a file in, and `.include /etc/hostname` comes back
  as `Error in line   <contents>` — in the log the user is reading. One regex
  now covers all four directives at both registration paths. 9 tests; all 7
  behavioural ones verified failing against the unfixed guard.
- API key: `ANALOG_LLM_API_KEY` overrides the stored one and the Settings
  dialog will not write it back. The keyring question stays open — this was
  the half that needed no dependency.
- GUI layer went from six modules at 0%. `test_ui.py` tests what every tab
  shares (job protocol, ngspice enable/disable, log, settings), not what each
  tab draws.
- Issue + PR templates; blank issues off, since the three facts a bug report
  here needs were exactly what nobody was being asked for.
- `analoggym/README.md`'s stale path moved to *Decided against*: the vendored
  tree stays untouched, both READMEs carry the note instead.
- Along the way the coverage run exposed a test writing into the real
  saved-runs store: `sizing.runs_dir` was patched on the package, not on
  `runs.py`. It passed on any empty machine and failed on the second run.
- Details: `cairn/pitfalls.md` → "A netlist is code", "Monkeypatching the
  sizing package patches nothing".

## 2026-09-10 · Windows CI hung 6 h on my own startup-dialog guard

- The v1.4 guard covered `QMessageBox.exec()` but not the Win32
  `MessageBoxW` fallback beside it; both block. The Windows job sat in
  `_report_fatal()` 16:06 → 22:04 and died on GitHub's six-hour limit.
- Fixed by guarding the whole function. Regression test forces
  `sys.platform` so it runs on every platform — against the broken code it
  fails in 1.6 s (verified by reverting the fix), rather than hanging.
- `pytest` job now has `timeout-minutes: 20`. A blocking test never fails on
  its own; the cap is what makes the next one cheap.
- Details: `cairn/pitfalls.md` → "A modal dialog needs someone to click it".

## 2026-09-10 · Default branch renamed to `main`

- The session-generated branch name was the repository's public face; it is
  now `main`. The rename and a push of mine crossed, which re-created the old
  name as a stray branch — deleted, its one commit moved onto `main`.
- `build-windows.yml` hard-coded the old name in its `branches:` filter, so
  until this change a push to `main` touching `app/` would have produced no
  builds, silently. That coupling was the reason to do the rename and the
  workflow edit together.
- Both READMEs' last-commit badge linked to `/commits/main` and 404'd; the
  rename fixed them without an edit.

## 2026-09-10 · v1.4 released — the repository's first

- Tag `v1.4` at `6e020a0`, five packages published. Build run 34462082771,
  all six jobs green including `release`, which had never executed before.
- The pre-emptive fix to that job was load-bearing, and the run proved it:
  `download-artifact` with `merge-multiple` put every file flat in
  `artifacts/`, including `AnalogStudio.exe` — so the old hard-coded
  `artifacts/AnalogStudio-windows-onefile/AnalogStudio.exe` would have
  matched nothing and failed the publish after ~36 min of building.
- The onefile exe is now a release asset rather than a 90-day artifact, so
  the outstanding "double-click does nothing" report can be retested any
  time.

## 2026-09-10 · Startup safety net + first-run splash

- Frozen builds are windowed, so a startup exception reached nobody. `main()`
  now writes `%TEMP%/AnalogStudio-crash.txt` and reports it; the dialog reuses
  an existing QApplication and falls back to the Win32 box, because Qt itself
  is a plausible cause of the failure.
- Building it produced a defect worth remembering: the first version's modal
  dialog **hung** under `--smoke`/offscreen (nobody to click OK) — CI would
  have timed out instead of failing fast. Guarded by `_interactive()`.
- Splash covers QApplication → main window, worded from
  `paths.first_run_expected()`. The scipy import before it cannot be covered:
  it must precede Qt (Nuitka Windows), so no QApplication exists yet.
- 5 tests. Details: `cairn/pitfalls.md` → "A modal dialog needs someone to
  click it".

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
