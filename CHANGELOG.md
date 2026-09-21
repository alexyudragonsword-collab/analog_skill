# Changelog — Analog Studio

All notable changes to the desktop app (`app/`). Versions before 1.0 were
development milestones and were never tagged — v1.4 is the first release;
vendored skill trees (`ngspice/`, `gmoverid/`, `transistor-models/`,
`circuit-skills/`, `analoggym/`) are archived as-is and never modified.

## vNext — unreleased

- **Every evaluation is archived, and a search can start from the best
  known point.** The optimizer appends each evaluated point (values and
  metrics, failures included) to a per-circuit JSON-lines archive in the
  user-data store (`sizing_archive/<circuit>.jsonl`). The Sizing tab
  shows how many points are archived and the best cost among them
  *under the targets as currently edited*, and a checkbox starts the
  search there instead of at the default sizing. Measured on two
  circuits and four target sets each (`cairn/pitfalls.md`): the archive
  re-scored under new targets beat a cold CMA-ES at 200 evaluations on
  six of eight sets with no model at all, and a warm start from it plus
  100 evaluations won seven, four to all targets met.
- **Warm starts use the finish's resume settings.** CMA-ES never
  evaluated its start point and took σ 0.25 from it; from a verified
  0.27 that gave a "best" of 0.73 after 100 evaluations. With a start
  point given, CMA-ES (plain and surrogate) now injects it into the
  first population and steps at σ 0.1; DE and Sobol+Powell already
  evaluated their start. `optimize(..., start=)` is the seam; the run
  notes say when a search was warm-started.
- **`cmaes_surrogate` — lq-CMA-ES as a pilot algorithm.** CMA-ES whose
  population is ranked by a linear-quadratic model of the evaluated
  archive (pycma's `fitness_models`, Hansen 2019): each generation
  evaluates points in the model's order until Kendall's tau between
  model and truth reaches 0.85, and the model ranks the rest. pycma's
  own loop is serial; this one batches each step's points across the
  workers. Failed evaluations rank last and stay out of the model. In
  the Sizing tab's algorithm menu as "CMA-ES + surrogate", not the
  default: measured on eight circuits at 600 evaluations it is better
  on two, worse on one and tied on five, but took twice the wall
  clock on every parallel circuit because pycma's tau-check schedule
  (1, 2, 3, 5 points a step) left workers idle. Each step is now
  filled to whole waves of `workers` points (4, 8, 12 on four workers);
  the run notes list the step sizes. Measured again: the wall clock
  now matches CMA-ES, and so does the result — 2–1 with five ties by
  small margins on one seed (`cairn/pitfalls.md`). Stays a pilot.
- **The four LDO variants report their own numbers now.** Every vendored
  LDO deck prints its output error as `vout − 4·Vref` and its quiescent
  current off a 1.8 V supply and a 5 mA floor — Basic_LDO's arithmetic,
  typed into all five. Only Basic_LDO and `ldo_1` have the 4:1 divider;
  `ldo_2`, `ldo_simple` and `ldo_folded_cascode` regulate to the
  reference itself, and two of them run from 2 V between 10 µA and
  10 mA. The reader (`_ldo_metrics`) now undoes each deck's arithmetic
  with a per-circuit bench table (`LdoBench`: regulated output, supply,
  the deck's Vref, the two load points). At the shipped defaults the
  output errors go from −4.8…−5.7 V to +5 mV, −30 mV, +3 mV and
  −0.31 V (the folded cascode's default really is low), and the
  quiescent currents from nonsense to 21 µA…1.6 mA. New metrics
  `vout_maxload` / `vout_minload` carry the reconstructed output. The
  vendored decks are untouched.
- LDO metric labels and circuit titles now state each circuit's real
  conditions (`1.8 V in, 1.6 V out, 5–55 mA`; `2 V in, 1.8 V out,
  10 µA–10 mA`) instead of Basic_LDO's on every variant. Load
  regulation is labelled for what the decks compute: a relative swing
  per ampere (`1/A`), not `V/A`.
- Tests: the bench table is checked against every deck's `.PARAM` and
  `alter` lines and the netlist's divider; the fold is unit-tested from
  a fabricated wrdata row; all four variants are evaluated at their
  defaults and their outputs must sit near their own reference.

## v1.6 — 2026-09-20

The search changed under this release and so did what it measures. The
two entries that matter to every user first: **a failed LDO simulation
used to report the previous point's numbers** (fixed below — every LDO
result from before this release is suspect), and **settling time is now
a target**, measured on a real step, which retired the phase-margin
ceiling and with it a whole class of over-compensated "feasible"
designs. Then the default search: **CMA-ES**, feasible on 12 of 18
circuit-seed rows against DE's 6 in the comparison, and on 12 of 22
circuits in a full sweep; with an **AI finish** behind it when a model
is configured, which asks three proposals a round and searches along
each. The Sizing tab names what is still short after a run and offers
the next step — seed, budget, finish — in one click, and a DE run can be
continued from its saved population. Known defect, unchanged in this
release: the four LDO variants' metric mapping is wrong; their numbers
should not be believed until it is read off each testbench.

- **Changed — no phase-margin ceilings anywhere.**  The amplifiers' went
  when settling time began measuring what over-compensation costs; the
  LDO and circuit-skills bands (60–90°) were the same guess without the
  measurement, and `ldo_basic`'s only misses in the full sweep were
  phase margins of 94° and 97°.  Floors of 60° stay.  The LDO's honest
  replacement is a load-step settling metric (ROADMAP).

- **Measured — the default on every circuit** (`cairn/pitfalls.md`, "The
  default on every circuit, once"): 12 of 22 feasible at seed 0, five
  of them with the search stopping early at cost 0.  The four LDO
  variants are excluded: their metric mapping is wrong at the shipped
  defaults (output error −5 V on a 1.8 V supply) and is recorded as a
  defect below.

- **Known defect — the four LDO variants' metrics.**  `ldo_simple`,
  `ldo_1`, `ldo_2` and `ldo_folded_cascode` have been registered since
  v1.4 with `ldo_basic`'s wrdata column order, which their testbenches
  do not follow; their offset and regulation numbers are not the
  quantities the labels say.  Found by the first sweep that ran them.
  They stay in the menu; nothing measured on them should be believed
  until the mapping is read off each testbench.

- **Changed — settling time replaces the phase-margin ceiling.**  Every
  amplifier evaluation now also steps a unity-gain follower by 100 mV
  (an instance the app appends to the rendered testbench, driven from
  the common-mode level; `tran 20n 20u`, about +0.1 s on a 5 s
  evaluation) and reports `tsettle`, the 1% settling time measured
  against the *commanded* step, and `overshoot`.  `tsettle` is the
  tenth amplifier target, 2 µs (4 µs on the 0.6 MHz CM OTA); phase
  margin is a floor of 60° again, no ceiling.  The measurement that
  decided it, on four reference-amplifier sizings:

  | phase margin | settle to 1% | overshoot |
  |---|---|---|
  | 156° (the design the ceiling was introduced against) | never (29 µs, still 23 mV short) | — |
  | 88° (CMA-ES, feasible under the band) | 0.90 µs | 2.4% |
  | 78° | 0.96 µs | 5.2% |
  | 40° | 1.44 µs | 31.5% |

  A ceiling caught the first row and nothing else; settling time
  charges both ends for what they cost.  Under the new spec the 88°
  design meets all ten targets and the 156° one costs 10.  Cost values
  on every amplifier change; earlier tables in `cairn/` say which rule
  they were measured under.  Wave capture carries the step (`t_step`,
  `v_step`) for a future panel.

- **Changed — the finish begins when the search stalls, not at a fixed
  point.**  `de_llm_finish` and `cmaes_llm_finish` used to hand the
  finish a fixed reserve from the end of the budget; on `ldo_basic` at
  seed 0 CMA-ES improved 1.08 to 0.84 in exactly those evaluations and
  the finish, given them instead, reached 1.05.  Now the search keeps
  its budget while it improves and stops for the finish after
  `STALL_EVALS` (60) evaluations without a new best, or at the latest
  with one finish round left; and for CMA-ES, whatever the finish
  leaves goes back to a CMA-ES restarted from the finished point with a
  tight step, so the budget is spent.

- **Fixed — the output clearing no longer deletes the deck.**  Two LDO
  variants name their testbench after their wrdata prefix
  (`ldo_simple_acdc.cir`, `ldo_simple_*`), and the first version of the
  clearing below removed the rendered deck before ngspice read it: every
  evaluation of `ldo_simple` and `ldo_folded_cascode` "produced no
  metrics" and a sweep scored both 95 at every point.  Clearing now
  happens before anything is written and never touches decks or
  parameter files; the variant test covers `ldo_simple`.

- **Fixed — circuit-skills evaluations clear the simulators' output
  files first.**  The same shape as the LDO phantom below: the vendored
  simulators write fixed filenames and parse whatever is there.  An
  audit after that fix found no other reader of this kind in `app/`.

- **Fixed — a failed LDO simulation no longer reports the previous
  point's metrics.**  `evaluate()` removed the old log before each run
  but not the LDO testbench's wrdata files; when ngspice died before
  writing them — an out-of-range device is enough — the reader took the
  slot's previous files as this point's result.  Two unrelated LDO
  sizings reported byte-identical metrics to seven digits, and a search
  could "find" a point whose numbers belonged to another.  Every output
  of the previous evaluation in a slot is now removed first, wave dumps
  included; a failed run comes back empty and is penalised as missing.
  **Every LDO number recorded before this entry is suspect** — the
  amplifier numbers are not, since their metrics come from the log,
  which was always cleared.  Re-measured (`cairn/pitfalls.md`): the
  phantoms were the good-looking numbers; the Powell polish honestly
  closes the LDO at seed 0 (9 of 18 feasible, was 8); CMA-ES's tallies
  stand; and the LDO's CMA-ES trajectories now reproduce to the digit,
  which closes the discrepancy recorded earlier.

- **Changed — each finish round asks three proposals, in parallel, and
  searches along all of them.**  The model's answer is not repeatable
  call to call: two sonnet runs from the same point, same prompt, named
  the same three variables and proposed different amounts — one cut the
  cost 37%, the other found nothing in three rounds.  One call is one
  draw from that spread; `FINISH_PROPOSALS` (3) takes its best.  One
  coarse scan covers every direction in a single batch, identical
  proposals collapse to one, and only the best line is refined.  The
  per-round reserve rises to 30 evaluations (from 16), the search phase
  holds back 90; wall clock per round is unchanged, since the calls run
  concurrently.  The Sizing tab's estimate says "3 AI rounds of 3
  calls".  Measured on the three CMA-ES endpoints from the opus/sonnet
  comparison: **three of three improved** (14%, 44%, 10%) where one
  proposal a round had improved one of three.  Then as shipped on nine
  circuits at two seeds: of the six rows CMA-ES leaves open it improves
  four (73%, 26%, 37%, 2%), leaves one, and ends worse than plain
  CMA-ES on one — `ldo_basic` seed 0, where the search was still
  improving when the reserve was taken from it.  Tables in
  `cairn/pitfalls.md`.

- **Changed — a round that improves nothing no longer ends the finish**
  (`FINISH_STOP_ON_STALL` is off).  The rule rested on five of five;
  asked anyway, the round after a failure has now paid three times in
  six, once by 44%.  With three proposals a round a failed round is
  three draws, not a verdict, and the next costs three parallel calls
  and thirty evaluations.

- **Changed — CMA-ES is the default search** when the `cma` package is
  present, with the AI finish behind it when a model is configured
  (`cmaes_llm_finish`, new); DE and DE + finish remain the defaults
  without the package.  The table behind the change is in
  `cairn/pitfalls.md`: nine circuits, two seeds, CMA-ES feasible on 12
  of 18 rows against DE's 6, best or tied on 16.  *Try next*'s "finish"
  suggestion names the CMA-ES form when it exists.

- **Added — `cmaes_llm_finish`.**  CMA-ES for all but the finish's
  reserve, then the same diagnose-and-search rounds as `de_llm_finish`.
  Run on the three places CMA-ES alone stops short: it takes
  `amp_ramos_pfc` (seed 1) from 0.4471 to 0.2836 in one round and finds
  nothing on `amp_leung_nmcf` (seed 1) or the LDO (seed 0) — the same
  shape as behind DE, a last-mile step for what is close, nothing for
  what is far.  Detail in `cairn/pitfalls.md`.

- **Removed — `de_portfolio`**, added earlier in this same unreleased
  section.  Measured at 1200 evaluations it lost on three of the four
  circuits it could run on and fell back to plain DE on the fifth: two
  generations per seed is too few to judge a seed by, and the
  evaluations spent on the discarded seeds are exactly what the
  continued one lacked.  What it was reaching for — try seeds, continue
  the best — is what the Seed box and *Continue* already let a user do,
  one full run per seed, which is the version that works.

- **Added — four more searches, each in the Sizing tab's algorithm menu,
  and one new dependency.**  Chosen for the shape of this problem
  (20–56 continuous variables, a piecewise cost that is flat in most
  directions once most targets are met, several basins per circuit) and
  the evidence so far (seeds disagree; DE converges by ~530; the finish
  turns close into done).
  - **CMA-ES with restarts** (`cmaes`, needs `cma`, pure Python, now in
    `requirements.txt` and forced into the frozen builds).  Covariance
    adaptation for the ill-conditioning DE ignores; IPOP restarts — a
    stalled run restarts with twice the population from a fresh point —
    for the basins.  Batches of max(workers, 4 + 3 ln dims).  Hidden from
    the menu when the package is absent, like Optuna.
  - **DE + Powell polish** (`de_powell`): DE for three quarters of the
    budget, bounded Powell from its best point with the rest.  The
    finish's line search without a model choosing the line.
  - **DE, constrained** (`de_constrained`): every metric a constraint
    under SciPy's feasibility rules — Lampinen's: an infeasible trial
    replaces its parent only if it is no worse on *every* metric, so a
    trade that fixes one target by breaking another is refused where the
    summed cost would take it — and the objective the summed margin
    inside the targets (`scoring.slack`, each margin capped at 50%), so
    the search keeps widening margins after the first feasible point
    instead of stopping there.  This is a different search before
    feasibility, not only after it; the first description here said
    otherwise and was corrected on reading SciPy's `_accept_trial`.  One parallel batch per generation: the
    constraint call sees the whole trial population and the objective
    reads what it cached — which requires SciPy's `vectorized` mode;
    without it the constraint is called one member at a time and the
    run is four times slower, as the first measured one was.
  - **DE portfolio** (`de_portfolio`): three seeds for half the budget,
    then the best population continued with the other half.  Needs
    twelve generations of budget (4 × dims each); below that it runs
    plain DE and says so in the notes.
  All four record their account in the run's notes.  (CMA-ES's IPOP
  restarts turned out never to fire on this problem — four runs at
  1200 evaluations, none stopped on pycma's tolerances, and the budget
  alone closed both LDO seeds; ROADMAP has the two options.)

  Measured, nine circuits, two seeds, the shipped path (tables and
  reading in `cairn/pitfalls.md`): **CMA-ES reaches feasibility on 12
  of 18 rows against DE's 6 and is best or tied on 16**, closing the
  reference amplifier under the 60–90° band at both seeds where nothing
  DE-based had; at 600 evaluations it beats DE at 1200 on three
  amplifiers.  Its restarts never fired at this budget — the win is
  plain CMA-ES.  The Powell polish is second (8 of 18); constrained DE
  closes 7 but with the worst total, its per-metric acceptance refusing
  too many trades; the portfolio loses three of the four circuits it
  can run on.  The default is unchanged in this entry; the numbers
  argue for CMA-ES on the amplifiers.

- **Added — a DE run keeps its last population and can be continued.**
  Re-running at twice the budget replays the first half exactly (same
  seed, same generations); `amp_leung_nmcf` at 1200 spent its first 552
  evaluations reproducing the 600-budget run.  Now `optimize()` records
  DE's final population in physical units with each member's cost on
  the run record, and `optimize(resume=run)` seeds the next search from
  it, serving those members from memory — every evaluation in the new
  budget is a new one, the previous best is the new curve's starting
  point, and the report says which run it carried on.  Physical units
  rather than normalized so an edited bound cannot shift the population
  silently; a changed bound simply means those points get re-simulated.
  Same circuit, same variables, DE-based algorithm only, else
  `ValueError`.  In the tab: *Try next*'s "more budget" step continues
  the run just finished instead of restarting at 2x (unless another seed
  did better, which is then the one to extend), and the Runs dialog has
  a *Continue* button for any saved run that kept a population.  *Use
  best as init* stays, for Sobol+Powell, where the init is the search.

- **Added — the Sizing tab now says what is still short and what to try
  next, and can do it in one click.**  After a run the status line names
  the missed targets in the same words the model is given ("Phase margin
  42.7 deg (want 60..90, off 29%)") and ends with a suggestion drawn from
  the measured order: **DE + AI finish** when the run is close (two
  misses or fewer, none over 10%) and the finish was not used; **another
  seed** while fewer than three have been tried at this budget; then
  **twice the budget at the seed that did best**.  A *Try next* button
  applies those settings and runs; circuit, bounds, targets and workers
  stay as they are.  The rule lives in `sizing.next_step()` and reads
  the saved runs, so the seed count survives a restart.  A **Seed** box
  sits under the budget.  The run record carries `algo`, `seed`,
  `budget` and the finish's round-by-round `notes`; the report prints
  the notes (which variables the model moved, what the line search
  found) and the search line; runs saved before these fields existed
  load with defaults.  `feedback_line` moved into `scoring` so the tab
  and the prompts print one sentence, not two.

- **Changed — defaults that stand on the evidence.**  Algorithm: DE + AI
  finish when a model is configured, DE otherwise (was Sobol+Powell,
  which at 60 evaluations in 33 dimensions did nothing).  Budget: 600
  (was 150, one DE generation on a 24-variable amplifier; the estimate
  label shows the cost).  Sobol+Powell stays in the menu.

- **Changed — the two circuit-skills gain targets are now what their
  boxes can reach: 36 dB on the five-transistor OTA (was 40), 64 dB on
  the two-stage (was 70).**  Only widths and bias vary in those boxes —
  channel length is fixed — so gm/gds is bounded, and differential
  evolution at 600 and 400 evaluations tops out at 37.4 and 65.7 dB, a
  few tenths above what the finish reached at a fifth of the budget.  A
  target no sizing in the box can meet turns every run into a miss; the
  new values leave about 1.5 dB of slack under the measured ceiling.

- **Added — `optimize(seed=)`.**  The Sobol sample, DE's population and
  Optuna's sampler took a hardcoded 0.  On this problem DE's endpoint
  depends on the seed a great deal (five seeds at 60 evaluations spanned
  0.66–3.31), so a second seed is the cheapest second opinion on any
  result, and the experiments below use it.  Not in the GUI yet.

- **Changed — phase margin is a band, 60–90°.**  The floor below was the
  right correction to the equality and the wrong stopping point: the
  first design it passed sat at 156°, its dominant pole below the 0.1 Hz
  sweep start, over-compensated in a way no other metric charged for.
  `MetricSpec` gains a `ceiling`; a `'max'` metric with one is penalised
  on both sides, `(m − ceiling)/ceiling` above.  Every amplifier, LDO and
  circuit-skills phase-margin spec carries `ceiling=90`; the GUI's target
  column still edits the floor only.  The CM OTA keeps its `≥ 55` with
  no ceiling, for the reason written next to it (single-pole, naturally
  ~90°).  Prompts, report and the targets table print the band
  (`max, <= 90`); the feedback line says `want 60..90`.  That 156°
  design now costs 1.1.

- **Changed — the finish runs up to three rounds, not one.**  Each round
  diagnoses from the previous round's best and searches along the new
  answer; the search phase holds back `FINISH_EVALS × FINISH_ROUNDS`
  (48) and each round is capped at its 16.  A round that improves
  nothing is reported to the model in the next prompt — the proposal,
  its rationale, "no point along it improved" — with an instruction not
  to repeat it, which is what makes a second round a second opinion.
  Why not re-run DE between rounds: it had converged (600 and 1200
  evaluations gave the same point), so re-running it returns the point
  the finish started from; the continuation that can change anything is
  another question.  Points are memoised across rounds — a later round
  from a new best often lands on the earlier proposal — and a line search
  whose best is its own start stops refining instead of bisecting
  toward zero.  The Sizing tab estimates `up to 3 AI calls`.

  **And it stops after a round that improves nothing** (a module switch,
  `FINISH_STOP_ON_STALL`, lets an experiment ask every round regardless).
  Validated on eight circuits of four kinds, shipped path, real CLI:

  | circuit | DE at its cap | after the finish | rounds | wall |
  |---|---|---|---|---|
  | amp_leung_nmcf | 1.4999 | 1.4999 | 3, none helped (PM 5°) | 17.7 min |
  | amp_peng_tcfc | 0.6695 | 0.5817 | 1 helped, 2 did not | 18.7 min |
  | amp_ramos_pfc | 1.3094 | 0.7784 | 1 helped (2 variables), 2 did not | 16.0 min |
  | amp_fan_smc | 0.4891 | **0.0000** | 3, each helped: 0.058, 0.001, 0 | 11.5 min |
  | studio_cm_ota | 0 | 0 | DE alone; finish skipped | 1.8 min |
  | ldo_basic | 0 | 0 | DE alone; finish skipped | 8.8 min |
  | skill_ota5t | 0.1731 | 0.1492 | 2 helped, 1 did not (gain 37 of 40 dB) | 2.5 min |
  | skill_opamp2 | 0.2215 | 0.1326 | 1 helped (IBIAS), 2 did not (gain 65 of 70 dB) | 5.1 min |

  Five of six finishes that ran improved in round one; the round after a
  failed round failed too, five of five, so a failed round now ends the
  finish (it cost nothing on any of the eight); `amp_fan_smc` needed all
  three rounds and got them.  Detail in `cairn/pitfalls.md`.

  The strongest single result came later, on the circuit the first
  sweep could not move: `amp_leung_nmcf` at seed 2 with 1200
  evaluations, DE to 1.10 with four targets short, the finish to
  **0 in two rounds** (bias current and three lengths, then input-pair
  width and bias current), all nine targets met in 15 minutes.

  *Correction, same day:* the reference amplifier re-run under the band
  (next paragraph) made that five of **six** — its third round improved
  8% after two failed ones.  The rule stays; the record is corrected.

  **The reference amplifier under the band is unsolved.**  Same shipped
  path, 616 evaluations: DE converges into the 156° basin the floor had
  called feasible (now cost 1.12, offset 3% over), and three rounds of
  finish move the phase margin only to 151°.  The ceiling removed a
  solution without supplying one; see ROADMAP for what would.

- **Added — `de_llm_finish`, the sixth sizing algorithm and the first
  one to meet every target on the reference amplifier.**  No model in the
  loop.  Differential evolution runs the search with all but the last
  `FINISH_EVALS` (16) evaluations; the model is then asked **once** what
  would fix whatever is still missed, told that the app will search along
  its answer; and a line search — a six-point scan at 0.25x to 2x the
  proposal, then three rounds of bisection around the best — spends the
  reserve.  Works with any LLM provider, since it is one `chat()` call
  with a one-candidate schema at the provider's default effort.

  The measurement it rests on, all on `amp_hoilee_affc`:

  | | cost | targets | wall |
  |---|---|---|---|
  | DE, 600 evaluations (seed 3) | 0.5076 | 8/9, PM 39.7° | 7.7 min |
  | DE, 1200 evaluations | **0.5076** | same point — converged by ~530 | 15.5 min |
  | + one LLM proposal, as written (6 tries) | 0.26–0.84 | 0 of 6 at PM 60 | +2.5 min |
  | + line search along that proposal | **0.004** in 3 of 6 | PM 59.8–60.2°, 8 intact | +21 s |

  Every proposal moved 2–3 compensation variables in the right direction
  by the wrong amount; the three that also widened the AFFC transconductor
  land, the three that touched only the capacitors stall with both at the
  top of their range.  Showing the model the operating point did not
  change the odds (2 of 3 with, 1 of 3 without), so the finish does not.
  The Sizing tab's estimate counts it as one AI call.

  Then the shipped path, as a user would run it — budget 616, four
  workers, DE's fixed seed, the real CLI: DE reaches 0.0276 at evaluation
  ~500 with only the input offset missed (105.5 µV against 100), the model
  moves the three input-pair variables and nothing else, and the six-point
  scan finds **cost 0.0000 — all nine targets met** — at 1.5x the
  proposal.  606 evaluations, 10.5 minutes.

  Look at that design before celebrating it: its phase margin is **156°**.
  The AC sweep says why — a dominant pole below the 0.1 Hz sweep start
  (the phase is already 150° at the first point, DC gain 144 dB), and the
  AFFC feed-forward zero lifts the phase back to 170° just below the
  single 1.26 MHz gain crossing.  Stable, one crossing, output at the
  same 0.45 V as every other sizing, six of thirty devices out of
  saturation against the usual seven.  Heavily over-compensated, and
  exactly what a *floor* on phase margin permits; the equality rule would
  have charged it 2.4.  Whether the spec wants a ceiling is in ROADMAP.
  Six proposals on one circuit chose what to build; one circuit and two
  runs do not put a number in the README (see ROADMAP).

- **Changed — phase margin is a floor (≥ 60°), no longer an equality.**
  Every amplifier, LDO and circuit-skills spec carried it as `'target'`,
  whose violation is zero only at *exactly* 60.000° — so `met` was never
  true and "all targets met", cost 0, and the feasibility question the
  whole LLM effort was chasing were unreachable by definition on those
  circuits.  A sizing at 59.86° read "8/9 met, off 0%".  Now `'max'`, as
  the CM OTA already had it at 55°: overshoot is free (its cost is speed,
  which GBW already charges for).  Cost values on those circuits change
  accordingly; earlier numbers in this file and in `cairn/` were measured
  under the old rule.  The `'target'` kind stays for overrides and custom
  circuits, with its behaviour noted at the definition.

- **The LLM search loop can carry the best sizing's operating point, and
  does not by default.**  It was switched on for a measured reason and
  switched off by two later ones, all three in this entry because the middle
  of that sequence is where the useful part is.

  *On:* one-shot proposals, n=4 vs 3 with zero overlap. Shown the operating
  point the model moves the four variables that size the offending devices
  **10–12x** more than the rest; without it that ratio is ~1, which is no
  targeting at all. It also moves less overall. Both p=0.029. The data
  reach the reasoning and are aimed correctly — that part still stands.

  *Off, reason one:* **the thing they aim at cannot be fixed by sizing.**
  The seven devices this circuit reports out of saturation are the same
  seven at the default sizing, at mid-range, at the low quartile and at the
  high quartile — the entire design space. They are a property of the
  topology, a bias mirror sitting 30–80 mV below Vdsat, not a fault.

  *Off, reason two:* **in the loop the targeting collapses.** Across
  fourteen rounds of a live run the implicated/other ratio went 0.0, 0.9,
  1.0, 1.7 and then **exactly 0.0 for the last ten** — the model stopped
  touching those four variables entirely while still moving everything
  else. Which is the right call: it tried them, cost did not move, it
  stopped paying. Feedback corrects the misdirection in about four rounds.

  So the measurable effect is four rounds down a dead end, for 5.6% wall
  time and ~10 kB of prompt per round. `LOOP_OPERATING_POINTS` keeps the
  mechanism — on a circuit whose out-of-saturation devices *are* fixable it
  could pay — but a default is set on evidence and this is the evidence.
  `sizing.operating_points()` is unaffected and still worth calling.

  **Correcting the v1.5 entry**, which cannot be edited because it is a
  published release note: it reported the declared metric coming back null
  as "handed a list naming seven devices in triode, the model did not fix
  them", framed as a negative result about the model. That framing was
  wrong. Nobody could have fixed them by sizing. The null was guaranteed by
  the metric, not earned by the model.

  Live-path numbers, since the previous entry said they were unknown: the
  prompt plateaus at ~83 kB by round 7 (the `HISTORY_ROUNDS = 6` window),
  the extra ngspice run costs 4.3 s and fires only on improvement (9 times
  in 60 evaluations), and the run finished 3.3123 → 1.2339 in 11.6 min —
  the best figure of any run this session and, at a 33% spread, worth
  nothing as evidence.


## v1.5 — 2026-09-15

A second LLM provider and a second sizing algorithm — but the two entries
that matter to every user are about neither. **Parallel evaluation could
install a half-extracted PDK**, silently, after which every simulation is
wrong; and **an imported netlist could read any file on disk** (v1.4 closed
the code-execution half of that, not this one). Both are listed below among
the rest.

- **Added — `sizing.operating_points()`, the layer under the nine metrics.**
  The metrics say *that* a sizing failed; the operating point says *why* —
  which device left saturation, which one is starved, where the headroom
  went.  It is the first thing a designer looks at and the one thing the LLM
  path has never been shown.  Captured by injecting `op` and a targeted
  `show` into the rendered control block, the same seam that already carries
  `set num_threads=1` and `wrdata`, so no vendored testbench is touched.
  Three things make it usable rather than a dump.  `show all` on this
  amplifier is **3.6 MB** and even `show m : id,vgs,vds,vdsat,vth,gm,gds` is
  37 kB of three-column blocks, so the output is parsed and re-emitted as
  one line per device — **3.1 kB** — carrying the ratios a sizing decision
  turns on (gm/ID, gm/gds, Vds−Vdsat) rather than raw volts and siemens.
  Devices are sorted worst-first, so truncation drops the ones nobody needed.
  And each line names the *variable* that sizes that device, read out of the
  netlist (`xm10 ... w='MOSFET_9_2_W_gm1_PMOS'`), because an operating point
  attributed to `xm10` is not something the model can act on.
  On the default `amp_hoilee_affc` sizing it reports 7 of 30 devices out of
  saturation, six of them on one bias mirror, with gm/gds of 1–3 against
  57–79 for the healthy ones.
  **Measured, n=5 per arm, one-shot "propose a sizing that fixes this":**

  | arm | out of saturation (baseline 7) | cost (baseline 3.31) |
  |---|---|---|
  | metrics only | 7 7 7 8 8 — median **7** | 9.26 11.49 14.41 15.21 15.39 — median **14.41** |
  | + operating points | 7 7 7 7 7 — median **7** | 7.74 8.08 8.15 8.39 13.23 — median **8.15** |

  The metric chosen up front — devices out of saturation, because that is
  what the operating point is *about* — came back **null** (U=8, p=0.09).
  Handed a list naming seven devices in triode and the variables that size
  them, the model did not fix them.  That is the headline and it is a
  negative one.
  The cost difference is a **secondary** metric and is reported as such
  rather than promoted because it is the one that moved: with-op proposals
  were better in **23 of 25 pairings** (Mann-Whitney U=2, one-sided
  p=0.016), median 8.15 against 14.41.  So the data appear to make
  proposals less bad, but not through the mechanism predicted — worth
  knowing, and worth not over-reading.
  Two caveats that matter.  **Both arms are far worse than the default
  sizing** (3.31), so this measures who fails less at a hard one-shot task,
  not who succeeds.  And a simpler explanation than "it reasoned about
  headroom" is available: the with-op prompt also *says* seven devices are
  already marginal, which may just make the model more conservative.
  Distinguishing those needs the proposals themselves, which this run did
  not keep.

- **Fixed — Cancel could not reach an agentic run.**  `llm_agent` is one CLI
  invocation that may be the entire search, and `subprocess.run()` offers no
  way in once it has started: pressing Cancel stopped `run_batch` accepting
  work, so the model got useless results and kept going until it finished on
  its own or hit a `budget x 25 s` timeout.  The call now runs under `Popen`
  with a watcher that kills the process — and on POSIX its whole session,
  since `claude` has an MCP server of its own running.  Measured: a child
  that would have run for 60 s is gone in about 3.  A cancel raises
  `CallCancelled` rather than `LLMError`, because the tabs render an
  `LLMError` as a red "Failed:" line and nothing failed.
  The round-based `llm` algorithm never had this problem — it checks between
  rounds, and a round is ~25 s.
- **`AGENT_EFFORT` is now a stated decision rather than an omission.**  The
  agentic loop was not passing `--effort` at all, which looked like a
  straightforward oversight.  On inspection it is the right value for the
  wrong reason, so it is written down instead of quietly copied from the
  other loop: `LOOP_EFFORT = 'low'` was justified by a measurement about
  **38 shallow turns** costing an hour, and the agentic loop takes a handful
  of turns that each read every result so far and decide what to do next.
  The thinking is the work there, and lowering it would save minutes rather
  than an hour, so the default stays the provider's.  `run_agent` accepts
  the parameter either way.

- **Added — an agentic sizing algorithm, where the model drives.**  The
  existing `llm` algorithm asks the model a fixed question each round and
  simulates its answer; `llm_agent` hands it one prompt and a tool and lets
  it decide what to try, how many at once, and when what it just learned
  changes its mind.  One CLI invocation covers the whole search.
  Mechanically: `EvalService` listens on loopback with a per-run token,
  `mcp_eval_server` is a stdlib JSON-RPC MCP server that forwards to it, and
  the CLI gets it through `--mcp-config` plus `--allowed-tools` — so the app
  keeps the budget, the Cancel flag, the parallelism and the ngspice scratch
  slots exactly where the other four algorithms already have them.  The
  disarming flags are unchanged and `--strict-mcp-config` still excludes the
  user's own servers, so the only tool in the session is this one.
  **It is not claimed to search better**, and on this project's measured
  33% run-to-run spread that claim could not be supported either way.  What
  it changes is the shape of the control loop.  A first real run (budget 12)
  spent 9 evaluations, improved cost 4.05 → 2.99, and came back with an
  account of *why* — that the input pair was undersized for the bias current
  and that the AFFC nested-loop cap restored phase margin better than the
  Miller cap — which the round-based loop has no way to produce.
  Requires the Claude Code provider; the HTTP providers are not wired for
  tool use here and the algorithm says so rather than failing obscurely.
- **Fixed — parallel evaluation could install a half-extracted PDK.**
  `ensure_sky130()` checked for the directory, then extracted into a temp
  tree whose name was fixed.  `optimize(workers=4)` evaluates on four
  threads and each one reaches it, so two could both find it missing — and
  the second `rmtree`d the first's tree *while it was still extracting into
  it*, after which the survivor could `os.replace` a partial PDK into place
  and every simulation afterwards would quietly be wrong.  It showed up as
  two "Extracting…" lines against one "ready".  Now serialized, re-checked
  inside the lock, and the temp name carries the pid so two processes do not
  collide either.  Found while running the agentic algorithm, unrelated to
  it, and older than both.

- **The LLM-guided optimizer was told a score and nothing else.**  Each
  round it got back `cand 1: {...} -> cost 0.83` — one scalar — and had to
  guess whether it was short on gain, long on power, or off on phase
  margin, and which targets had slack to trade.  The information existed
  the whole time: `_eval_one` computed the full nine-metric dict, scored
  it, and returned only the number.  Now the feedback reads

      cand 1: {...} -> cost 1.3980  [6/9 met; DC gain 62.1 dB
      (want >= 100, off 38%); Power 0.00081 W (want <= 0.0005, off 62%);
      Phase margin 59.2 deg (want = 60, off 1%)]

  which is the difference between a directed move and a wander.  Only the
  worst few misses are named and the rest are counted, so a deck that fails
  everything cannot paste nine clauses into every candidate of every round.
  `score()` is now `sum(score_detail())` rather than a second
  implementation of the same arithmetic — the cost the optimizer minimizes
  and the breakdown the model is shown cannot drift apart.  `run_batch`
  takes `with_metrics`; every other algorithm still gets the bare list of
  costs it always wanted.
  **The A/B went against it, and the experiment cannot resolve that.**
  One run per arm, `amp_hoilee_affc`, 60 evaluations:

  | evals | 10 | 20 | 30 | 40 | 50 | 60 | best |
  |---|---|---|---|---|---|---|---|
  | with metrics | 2.135 | 2.025 | 1.900 | 1.899 | 1.899 | 1.495 | **1.4954** |
  | cost only | 2.840 | 2.590 | 1.666 | 1.384 | 1.384 | 1.380 | **1.3798** |

  The arm *with* the extra information finished 8.4% worse.  Before reading
  anything into that, note what the earlier effort A/B accidentally
  provided: its `low` arm is the same configuration as this one's
  `cost only` arm, and the two runs came out at 1.3182 and 1.3798 — **4.6%
  apart with nothing changed**.  So the effect here is 1.9x a noise range
  measured from a single pair, which is not a result in either direction.
  **Replicated to n=3 and n=4, and the answer is that this experiment
  cannot answer it:**

  | arm | runs (best cost, sorted) | median |
  |---|---|---|
  | with metrics | 1.2365 · 1.4954 · 2.8274 | 1.4954 |
  | cost only | 1.3182 · 1.3738 · 1.3798 · 1.7504 | 1.3768 |

  The best run of the entire experiment used the metric breakdown (1.2365);
  so did the worst (2.8274), and no run hit an LLM fallback, so that was a
  real search failure rather than a plumbing one.  The `cost only` arm's own
  spread across four runs is 1.3182 to 1.7504 — **33%**, which retires the
  4.6% noise figure estimated from the first two runs; a two-run replicate
  understates spread badly.  Separating an ~8% effect from a 33% spread
  needs on the order of (33/8)² more runs per arm — dozens, several hours.
  The feature is kept as a **judgment call, explicitly not a measured win**:
  the information-asymmetry argument stands on its own, no harm survives the
  noise, and the extra cost is some cached input tokens.  The thing to watch
  is variance rather than mean — this arm produced both tails.
  Kept regardless of any of it: `score()` as the sum of `score_detail()` is
  correct whether or not the model reads the breakdown, and the loop having
  been handed one scalar is a fact about the design, not a finding.
  Also caught while making the change: `objective()`, which feeds Powell,
  returns `_safe_eval(...)` — which had just become a tuple.  The default
  algorithm would have broken.

- **Added — `chat(effort=...)`, and the sizing loop now asks for "low".**
  Almost none of a Claude Code call is overhead: measured on
  `amp_hoilee_affc`, startup is **1.0 s of 101**, and the other 100 s is the
  model generating — mostly reasoning, not answer.  The same prompt, model
  and schema at three effort levels:

  | effort | wall | output tokens | candidates |
  |---|---|---|---|
  | default | 101 s | 11 128 | 4/4 |
  | medium | 49 s | 7 380 | 4/4 |
  | low | **25 s** | 3 520 | 4/4 |

  The answer stayed ~3 950 characters throughout; what disappeared was
  thinking.  For a 150-evaluation run that is roughly an hour of model time
  against sixteen minutes.  The search loop asks for `low` — it runs ~38
  times a run, proposing points near the current best — while
  `suggest_setup` and `explain_run` leave the provider's default alone,
  because each is called once and the user reads the result.
  **The A/B is in** — one run per arm, `amp_hoilee_affc`, 60 evaluations,
  cost by evaluation count:

  | evals | 10 | 20 | 30 | 40 | 50 | 60 | wall |
  |---|---|---|---|---|---|---|---|
  | low | 1.632 | 1.338 | 1.333 | 1.328 | 1.323 | **1.318** | 12.3 min |
  | default | 3.312 | 2.494 | 1.534 | 1.534 | 1.281 | **1.280** | 26.0 min |

  Read per *evaluation*, the default is 3% better (1.280 vs 1.318) — a gap
  a single run cannot separate from noise.  Read per *minute*, which is the
  budget a person sitting in front of the app actually spends, `low` is far
  ahead: at the 12.3 minutes it needed to finish, the default arm was at
  1.534, and `low` had already been below that since evaluation 20.  The
  saved time also buys evaluations — 120 of them at `low` costs about what
  60 cost at the default.  So `low` stands, on the equal-time comparison
  rather than the equal-budget one.  What the curves do show is a real
  difference in shape: `low` drops fast and plateaus, the default keeps
  descending and edges past it at the very end.  Worth revisiting if a
  circuit turns up where that plateau matters.
  The measurement also ruled out the two ideas that looked more promising:
  batching rounds into one CLI invocation would save that 1.0 s, and a
  smaller model is not the lever either — haiku ran **slower** than sonnet
  (117 s), spending more tokens to reach the same place.
- **Fixed — the time estimate would have overstated LLM runs fourfold.**
  Its per-round constant was measured at the provider default; the loop now
  runs at `low`. It follows the effort instead of assuming one.

- **Added — `chat(schema=...)`, so a reply's shape can be enforced instead
  of hoped for.**  The LLM sizing loop asks for candidates as JSON, and
  `_parse_candidates` requires every candidate to carry every variable name
  verbatim — 24 for the median circuit, **56 for `ldo_2`**, names like
  `MOSFET_0_8_L_BIASCM_PMOS`.  A candidate missing one key is dropped
  *silently*; if all of them are, the round retries once and then falls back
  to random Sobol samples, spending real evaluation budget on unguided
  points.  Over the ~37 rounds a 150-evaluation run takes, that is a bet the
  model loses eventually.  A JSON Schema built from the circuit's own
  variables makes the shape unbuildable-wrong, and carries the per-variable
  bounds too, so proposals stop landing outside the box only to be clipped
  onto an edge.  `suggest_setup` gets a schema as well — a partial one, since
  it asks for "only variables worth changing", but one that stops it naming
  a variable the circuit does not have.
  The parameter is a **request, not a guarantee**: Claude Code enforces it
  via `--json-schema`, the HTTP providers ignore it for now and keep their
  `extract_json` path, and no caller has to know which is which.
- **Fixed — the LLM algorithm would have timed out on any wide circuit.**
  Measured on `amp_hoilee_affc` (33 variables, a 7.4 kB prompt, four
  candidates asked for): **88 s with a schema, 112 s without**.  `chat()`
  defaults to a 120 s timeout, so a round would intermittently time out,
  retry for another two minutes, and then fall back to Sobol — the LLM
  algorithm quietly ceasing to be the LLM algorithm.  The CLI provider's
  timeout floor goes from 90 s to 300 s.  Also worth recording: the schema
  turned out to be *faster* than freeform, so this is the cost of the
  workload, not of the constraint.
- **Fixed — the Sizing tab's time estimate ignored the AI.**  It counted
  `eval_seconds x budget / workers` and read "≈ 2 min" for an LLM run whose
  ~38 model calls take closer to an hour.  It now adds the rounds and says
  how many.

- **Added — the AI features can run on a Claude subscription instead of an
  API key.**  A third provider, *Claude Code CLI*, drives the locally
  installed `claude` binary, which already carries the user's own login.
  Settings swaps the API-key row for a path box (empty = find it on PATH)
  and its Test button reports the CLI version before asking it anything.
  `chat()`'s contract is unchanged, so `llm_sizing` needed no edits: the CLI
  takes one prompt rather than a message array, and the history is flattened
  into it — which is the same conversation the HTTP providers get re-sent on
  every call anyway.
  **The CLI is disarmed before it is used.**  This spawns an agent on the
  user's machine, so it is run `--restricted` (no shell, no code execution,
  no WebFetch), with the remaining file tools in `--disallowed-tools`, with
  `--setting-sources ''` and `--strict-mcp-config` so the user's own
  `CLAUDE.md`, hooks and MCP servers cannot steer a transistor-sizing
  prompt, in an empty scratch directory, and never with
  `--dangerously-skip-permissions`.  It also pins a fresh `--session-id` per
  call: without one the CLI joins a session inherited from the environment,
  which happens whenever the app is launched from inside a Claude Code
  session — a sizing prompt would land in the user's own conversation.
  Measured against claude 2.1.270: ~4–6 s per call against ~1–2 s for a
  direct API request, so the Test button's timeout has a floor that a
  15-second HTTP timeout would have tripped over.
- **Fixed — "LLM not configured" gave advice that did not fit the
  provider.**  It told every user to set an API key, including the ones
  whose provider has no API key to set.  The message is now chosen per
  provider, in one place both call sites share.

- **The GUI tests now cover what a tab does with a reply.**  The previous
  round got every tab off 0% by constructing it; this one drives the half
  that actually breaks.  Three rules are now locked down across all six
  tabs: a failed job always re-enables the control the user pressed (a tab
  that forgets is dead until restart — the job is gone and nothing else will
  re-enable it); a render closure that raises is reported as red text rather
  than thrown inside a Qt slot; and the gm/ID tab both discards a table built
  for parameters the user has since changed and clears the previous table on
  a failed rebuild, so the lookup tools cannot keep answering from it.  Plus
  the Sizing tab's full round trip — press Run, hand back a finished run,
  check the buttons, the report and that it was saved — driven with a
  fabricated result instead of a real optimization, which keeps the suite at
  ~2.5 min.  Verified by mutation: breaking either guard fails the test.
  133 tests, `app/` coverage 69% → 71%.
- **Decided — no `keyring` dependency, and Cairn stays unconnected.**  Both
  questions were open pending a judgement rather than work; both are now
  answered in `ROADMAP.md`'s *Decided against*, with the reasoning and the
  condition that would reopen them.

- **An imported netlist could read any file on your disk.**  The v1.4 guard
  closed the code-execution path (`.control`, which ngspice runs and which
  may call `shell`) but deliberately left `.include` open so the two could be
  judged separately.  Measured against ngspice-42, the answer is that it
  should have been closed as well: `.include`, its `.inc` abbreviation and
  `.lib` all pull a file into the simulation — case-folded, space- or
  tab-indented, path bare or in either quote style — and the contents come
  back in the run log the user is looking at (`.include /etc/hostname`
  surfaces as `Error in line   <the file>`).  The read is not merely
  attempted, it is reported.  The amplifier contract needs no includes at
  all and no shipped netlist or variables file uses one, so all four
  directives are now refused at both registration paths, in the netlist and
  in the `.PARAM` file.  9 regression tests, one of which proves ngspice
  really does echo an included file so the guard cannot quietly become
  pointless.
- **Added — the LLM API key can be kept off disk.**  `QSettings` stores it in
  plain text (the registry on Windows, an ini file elsewhere), which is fine
  for a key you pasted in on your own machine and not fine on a shared one.
  `ANALOG_LLM_API_KEY` in the environment now overrides the stored key; the
  Settings dialog shows it read-only and — this is the part that matters —
  does not write it back when you press OK, which would have put it on disk
  after all.  The dialog now also says plainly where the key is kept.  A
  `keyring` dependency would solve the general case but has to survive three
  freezing toolchains; that stays open in `ROADMAP.md`.
- **Fixed — the startup error dialog could hang forever on Windows.**  The
  v1.4 safety net put `QMessageBox.exec()` behind an `_interactive()` check
  but left the Win32 `MessageBoxW` fallback outside it, and that call blocks
  until someone presses OK just as hard.  On the Windows CI runner nobody
  can: the job sat inside `_report_fatal()` from 16:06 to 22:04 and was
  killed by GitHub's own six-hour limit — the exact failure mode the guard
  was added to prevent, reintroduced in the branch next to it.  Both dialogs
  now sit behind the one check.  The regression test forces `sys.platform`
  so it runs everywhere rather than only on Windows; against the broken code
  it fails in 1.6 s instead of hanging.  The `pytest` job also gained
  `timeout-minutes: 20` (the suite takes ~3): a test that blocks on a modal
  dialog never fails on its own, so the cap is what turns the next one into
  a red job in minutes rather than a wasted afternoon.
- **The GUI layer has tests.**  Six UI modules were at 0% — everything the
  user actually clicks.  `app/tests/test_ui.py` covers the parts that are
  shared and fail the same way in every tab: the `JobTabMixin` protocol
  (which reply belongs to which slot, and that a tab drops another tab's
  replies), that a missing ngspice disables all six tabs rather than five,
  that a failed job reaches the log panel in full, the Settings round trip,
  and that both manual languages are really shipped.  Layout and geometry
  are deliberately not tested.  Coverage of `app/` went from 50% to 69%.
- **Fixed — a test was writing into the developer's real saved-runs store.**
  `test_runs_dialog_and_warm_start` patched `sizing.runs_dir`, which is the
  package re-export; `save_run()` and `list_runs()` resolve that name in
  `runs.py`'s own globals, so the patch did nothing and both worked on the
  real user-data directory.  It passed on a machine that had never run it and
  then counted the previous run's files on the second go — which is how it
  finally surfaced, as `assert 4 == 2`.  This is the monkeypatch pitfall
  `CONTRIBUTING.md` warns about, in the suite that documents it.
- **Issue and PR templates.**  A bug report here is unusable without the
  build, the platform and the ngspice version, and nothing asked for them;
  the bug form now requires all three and blank issues are off.  The PR
  template carries the checks that CI runs anyway, plus the two rules that
  CI cannot see — CHANGELOG in the same commit, and no vendored tree touched.

## v1.4 — 2026-09-10

Design import + netlist viewer in the Sizing tab.

- **The release job would have failed on its first run.**  Nothing had ever
  exercised it — the repository has no tags — and one of its five hard-coded
  artifact paths assumed a different `download-artifact` layout than the
  other four, which with `fail_on_unmatched_files` would have failed the
  publish at the last step.  It now flattens whatever was downloaded, lists
  it, and refuses to publish unless all five packages are there (verified
  against both possible layouts).  It also refuses while the top CHANGELOG
  section still says *unreleased*, since that text becomes the release notes
  verbatim.
- **A failing startup is no longer silent, and a slow one says so.**  The
  frozen builds run windowed (`--windows-console-mode=disable`), so any
  exception before the window appeared reached nobody — the symptom is the
  reported "double-click does nothing".  `main()` now writes the traceback
  to `%TEMP%/AnalogStudio-crash.txt` and names that file in an error
  dialog.  The dialog deliberately does not create a `QApplication` of its
  own: when Qt itself is what broke (a missing libEGL or VC runtime, a bad
  DLL in the bundle) constructing one would just fail again, so an existing
  instance is reused, Windows falls back to a native message box that needs
  no Qt, and everyone else gets stderr — which the frozen builds already
  redirect to a file.  It is also skipped under `--smoke` and the
  offscreen/minimal Qt platforms: a modal box blocks until someone clicks
  OK, and raising one where nobody can would hang CI until the job timed
  out instead of failing fast (measured while building this — the first
  version did exactly that).
  A splash screen now covers the work between `QApplication` and the main
  window, worded from `paths.first_run_expected()` so a first launch says
  "unpacking bundled assets, one time only" rather than showing a frozen
  cursor.  The scipy import before it stays uncovered by design: it must
  precede any Qt import (Nuitka Windows access violation), so there is no
  `QApplication` yet to draw on.
  Both READMEs now warn that the unsigned builds trip SmartScreen, and
  point at the crash file.
- **Fixed — an imported netlist could run arbitrary commands.**  ngspice
  executes `.control ... .endc` blocks in batch mode, and such a block may
  call `shell`.  Both the imported netlist and its .PARAM file are
  `.include`d verbatim into the rendered testbench, and a directive inside
  an included file executes exactly as if it were inline — so a design
  taken from a paper's supplement or a forum could run commands on the
  first evaluation while every metric still came back looking normal
  (reproduced end to end through `import_user_circuit` → `evaluate`: the
  payload ran, the report showed `tc`/`ivdd25`/`power` as usual).  Import
  now refuses any netlist or design-variables file containing a control
  block, and `load_user_circuits()` re-checks files already in the store
  rather than trusting them, so a design imported before this check
  existed does not become runnable just by being on disk.  The amplifier
  contract is a plain `.subckt` and none of the 27 shipped circuits
  contains a control block, so nothing legitimate is refused.  The manual
  states the trust boundary in both languages.
- **Project Cairn initialized**.  `AGENTS.md` becomes the always-read rules
  and navigation entry point (Codex reads it directly; `CLAUDE.md` is now the
  one-line `@AGENTS.md` stub Cairn expects), with `.cairn/config.yaml` holding
  the machine-readable config and `cairn/` the knowledge layer.  The previous
  96-line `CLAUDE.md` was not discarded: its rules and commands moved into
  `AGENTS.md`, and its six failure modes — the sizing package's monkeypatch
  seam, workspace vs user data, ngspice's unquoted `.include`, GUI-thread
  matplotlib, schemdraw version sensitivity, concurrent test suites — became
  `cairn/pitfalls.md`, where each now carries what it actually cost.
  `git_policy: track` (the knowledge layer is committed; the repository is
  public, so nothing private may be written there), graduation provider
  deferred, and `migration_mode: inventory_only` — the pre-Cairn documents are
  inventoried in `cairn/existing-knowledge.md`, not rewritten.  `ROADMAP.md`
  deliberately stays at the repository root instead of moving under `cairn/`.
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
  Code, previously git-ignored alongside local settings — since folded into
  `AGENTS.md`, see above).  New
  `ROADMAP.md` — until now open work existed only in commit history and
  conversation, so nothing recorded what was pending or, just as usefully,
  what had already been decided against.  The Sizing
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
