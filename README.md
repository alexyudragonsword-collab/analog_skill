<p align="center">
  <img src="openclaw.png" alt="Analog Studio" width="100%">
</p>

<h1 align="center">Analog Studio</h1>

<p align="center">
  <a href="https://github.com/alexyudragonsword-collab/analog_skill/stargazers"><img src="https://img.shields.io/github/stars/alexyudragonsword-collab/analog_skill?style=flat-square&color=f5c542&logo=github" alt="GitHub stars"></a>
  <a href="https://github.com/alexyudragonsword-collab/analog_skill/commits/main"><img src="https://img.shields.io/github/last-commit/alexyudragonsword-collab/analog_skill?style=flat-square&color=3fb950" alt="Last Commit"></a>
  <a href="https://github.com/alexyudragonsword-collab/analog_skill/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/alexyudragonsword-collab/analog_skill/test.yml?style=flat-square&label=tests" alt="Tests"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue.svg?style=flat-square" alt="Python 3.11">
  <img src="https://img.shields.io/badge/Qt-PySide6-41cd52.svg?style=flat-square" alt="PySide6">
  <img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License: MIT">
  <img src="https://img.shields.io/badge/ngspice-required-orange.svg?style=flat-square" alt="ngspice required">
</p>

**A desktop workbench for analog IC design, on top of real SPICE.** Size a
transistor from a gm/ID target, browse device characteristics across 40 PTM
models, run block-level circuits, and let an optimizer search a 27-circuit
library of SKY130 topologies against your own spec targets — all driven by
ngspice on your machine, no cloud, no PDK licence.

<p align="center">
  <img src="app/resources/manual/img/v14_sizing.png" alt="Analog Studio — Sizing tab" width="82%">
</p>

The repository also archives the three Claude **skills** the app grew out of
(`ngspice`, `gmoverid`, `transistor-models`) — see
[Claude skills](#claude-skills) below if that is what you came for.

---

## What it does

| Tab | What you get |
|---|---|
| **gm/ID Designer** | 40 selectable models — 20 PTM bulk (180/130/90/65 nm and 45/32/22 nm HP/LP, n+p) and 20 PTM-MG **FinFET** (7/10/14/16/20 nm HP/LSTP, via ngspice's OSDI BSIM-CMG, sized by **NFIN**). Build a `GmIdTable` lookup (first run simulates and caches), then size by gm/ID, by fT target, or by gm·ro target. Engineering-unit result table plus a 2×2 design plot with the operating point marked. |
| **ngspice Examples** | The nine teaching examples (DC / AC / Tran / Noise) one click each, with VDD, sweep ranges, frequencies, timing and temperature exposed in a collapsible *Advanced* group. |
| **Curve Browser** | Generate and page through characterization plots per model/L/W: IV, the gm/ID four-quadrant set, gate capacitance. Cached per session. |
| **Comparison** | Channel-length sweeps (L = 180/360/1000 nm), cross-node comparisons, cross-node gate capacitance. |
| **Circuits** | Five block-level circuits — StrongArm comparator, LDO, bootstrapped switch, 5T OTA, two-stage Miller op amp — each with its schematic drawn from the DUT netlist, editable parameters and a copyable metric report. |
| **Sizing** | Automatic device sizing over **27 circuits**: 20 SKY130 designs from the vendored [AnalogGym](https://github.com/CODA-Team/AnalogGym) subset (15 published three-stage Miller op amps + Basic LDO + 4 LDO variants), 1 original current-mirror OTA, and 6 PTM circuit-skills entries. Editable bounds and metric targets with **hard constraints**; four optimizers (built-in Sobol+Powell, differential evolution, Optuna TPE, and an **LLM-guided** loop); parallel evaluation; convergence curve, before/after wave overlays, per-device change summary, run history, and import of **your own SKY130 amplifier**. |

Every simulation runs on one background thread, so ngspice scratch files never
collide; the skills' own `print` progress is forwarded live to the log panel.
Help ▸ Manual (F1) opens an illustrated manual in English and Chinese.

## Install

### Prebuilt (no Python needed)

Windows and Linux packages are built on every push by
[`build-windows.yml`](.github/workflows/build-windows.yml) — PyInstaller and
Nuitka, plus a single-file Windows `.exe`. Grab them from the **Actions** tab
of a green run, or from **Releases** once a version is tagged.

**ngspice is not bundled.** On Windows, download the zip from
[ngspice.sourceforge.io](https://ngspice.sourceforge.io) and extract `Spice64/`
next to the executable (or point at it in Settings). On Linux/macOS install it
from your package manager.

**On Windows, the first launch is slow and SmartScreen will warn.** The builds
are unsigned, so SmartScreen shows "Windows protected your PC" — choose *More
info* → *Run anyway*. The first run then unpacks the bundled assets (~100 MB
for the single-file build) before the window appears, which takes a while on a
cold disk; a splash screen says so. If nothing at all happens, look for
`AnalogStudio-crash.txt` in your `%TEMP%` folder — the app writes the reason
there rather than failing silently.

### From source

```bash
git clone https://github.com/alexyudragonsword-collab/analog_skill
cd analog_skill
pip install -r requirements.txt
sudo apt install ngspice        # or: brew install ngspice
python -m app.main
```

Requires Python 3.11 and ngspice (42 or newer recommended; FinFET models need
OSDI support, i.e. ngspice ≥ 38). See [`APP_README.md`](./APP_README.md) for
architecture, packaging and the ngspice detection order, and
[`CONTRIBUTING.md`](./CONTRIBUTING.md) to work on the code.

## What is in this repository

| Path | |
|---|---|
| `app/` | The application. Everything here is written for this project (MIT). |
| `tools/` | Schematic generators — the circuit drawings are rendered from the netlists, not screenshotted. |
| `studio_circuits/` | Circuits authored here for the Sizing tab (MIT). |
| `ngspice/`, `gmoverid/`, `transistor-models/` | The three Claude skills, archived **as-is**. |
| `circuit-skills/` | Vendored [analog-circuit-skills](https://github.com/Arcadia-1/analog-circuit-skills) — the five block circuits. |
| `analoggym/` | Vendored open subset of [AnalogGym](https://github.com/CODA-Team/AnalogGym) (ICCAD'24, BSD-3) backing the Sizing tab. |

The vendored trees are upstream snapshots and are never modified — the app
reads them from disk exactly as shipped.

### Documentation

| | |
|---|---|
| [`APP_README.md`](./APP_README.md) | App architecture, running from source, packaging (5 build variants), code layout |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Tests, lint, regenerating schematics, CI, release |
| [`ROADMAP.md`](./ROADMAP.md) | What is open, what is blocked, and what was decided against |
| [`CHANGELOG.md`](./CHANGELOG.md) | Every release, what changed and why |
| [`CODE_PROTECTION.md`](./CODE_PROTECTION.md) | What the Nuitka builds do and do not protect |
| In-app manual (F1) | The user-facing guide, English + Chinese |
| [`ANALOG_REPOS_ANALYSIS.md`](./ANALOG_REPOS_ANALYSIS.md), [`CIRCUIT_SKILLS_ANALYSIS.md`](./CIRCUIT_SKILLS_ANALYSIS.md), [`ANALYSIS_REPORT.md`](./ANALYSIS_REPORT.md) | Dated analyses of the upstream projects, kept as historical records |

---

## Claude skills

Three skill packages that give an agent the ability to design and simulate
analog circuits. They are archived here unmodified; the app builds on them but
they remain usable on their own.

| Skill | For | Contents |
|---|---|---|
| **ngspice** | Beginners | 9 standard simulation examples (DC / AC / Tran / Noise) |
| **gmoverid** | Design work | gm/ID characterization + a design API that looks up W, Id, Vgs, fT and gm·ro |
| **transistor-models** | Model library | The full PTM set: bulk 180–65 nm, HP/LP 45–22 nm, FinFET 20–7 nm |

<details>
<summary><b>Install the skills into Claude Code</b></summary>

Globally, for every project:

```bash
git clone --depth 1 https://github.com/alexyudragonsword-collab/analog_skill /tmp/analog_skill \
  && cp -r /tmp/analog_skill/{ngspice,gmoverid,transistor-models} ~/.claude/skills/ \
  && rm -rf /tmp/analog_skill
```

Or for the current project only, replacing `~/.claude/skills/` with
`.claude/skills/`. Then run `/skills` in Claude Code — the three names should
appear. Each skill's full instructions are in its own `SKILL.md`; runnable
scripts and model files are under its `assets/`.

</details>

<details>
<summary><b>Skill 1 — ngspice: nine teaching examples</b></summary>

| # | Type | Description |
|---|---|---|
| 1 | Tran | RC charging voltage and current |
| 2 | DC | NMOS Id-Vds family of curves |
| 3 | AC | RC low-pass filter frequency response |
| 4 | Noise | RC filter output noise spectral density |
| 5 | Tran | Sample-and-hold switch comparison |
| 6 | Tran | kT/C noise time-domain statistics |
| 7 | DC | NMOS current mirror output characteristics |
| 8 | AC | Common-source amplifier Bode plot |
| 9 | DC | Transmission-gate on-resistance |

![NMOS Id-Vds](dc_nmos_iv.png)
![RC low-pass filter](ac_rc_bw.png)

</details>

<details>
<summary><b>Skill 2 — gmoverid: characterization and the design API</b></summary>

Each process node produces three standard plot sets: an IV 2×2, the gm/ID
four-quadrant 2×2, and gate capacitance vs Vgs.

![gm/ID four-quadrant](gmoverid_nmos45hp_L45nm.png)

The four quadrants are gm/ID vs Vov (with the BJT limit q/kT = 38.6 V⁻¹ and the
2/Vov asymptote drawn in), Id/W vs gm/ID over ~3 decades, fT vs gm/ID (PTM
180 nm peaks near 50 GHz, 22 nm HP exceeds 600 GHz), and gm·ro vs gm/ID
(180 nm reaches ~40–42 in weak inversion; 22 nm HP is only 2–4 because of
short-channel effects).

```python
from design_gmoverid import GmIdTable, print_op

tbl = GmIdTable('nmos180', W=10.0, L=0.18, vds=0.9)
op = tbl.size(gmid=15.0, Id=100e-6)   # fix gm/ID and Id, solve for W
op = tbl.size_from_ft(5e9, W=20.0)    # fT >= 5 GHz at the lowest power
print_op(op)
```

The first call runs ngspice and caches the result; later calls read the cache.
Three models ship with the skill (180 / 45 / 22 nm) — install
`transistor-models` for the rest.

</details>

<details>
<summary><b>Skill 3 — transistor-models: the PTM library</b></summary>

PTM (Predictive Technology Model) is a public SPICE model set from Arizona
State University, for process exploration and teaching where no PDK is
available. This skill packages everything from
[mec.umn.edu/ptm](https://mec.umn.edu/ptm):

- Bulk silicon: 180 / 130 / 90 / 65 nm
- Bulk HP/LP: 45 / 32 / 22 nm
- PTM-MG FinFET: 20 / 16 / 14 / 10 / 7 nm, HP + LSTP

Copy what you need into your project's `models/`:

```bash
cp transistor-models/assets/models/bulk_cmos/ptm32lp.lib <project>/models/
cp transistor-models/assets/models/finfet/nmos7mg_hp.lib <project>/models/
```

Naming: `bulk_cmos/ptm{node}{hp|lp}.lib` and `bulk_cmos/ptm{node}.lib` contain
NMOS + PMOS as `nmos`/`pmos`; `finfet/{n|p}mos{node}mg_{hp|lstp}.lib` use
`nfet`/`pfet`. Full parameter table:
[`transistor-models/references/model_params.md`](./transistor-models/references/model_params.md).

</details>

## Licence and citations

The application, `tools/` and `studio_circuits/` are MIT (see
[`LICENSE`](./LICENSE)). Vendored trees keep their own terms — AnalogGym is
BSD-3 ([`analoggym/LICENSE`](./analoggym/LICENSE)).

The PTM model files are copyright the ASU PTM project and free for academic
research. Please cite:

- Bulk CMOS nodes:
  > W. Zhao and Y. Cao, "New Generation of Predictive Technology Model for Sub-45 nm Early Design Exploration," *IEEE Transactions on Electron Devices*, vol. 53, no. 11, pp. 2816-2823, Nov. 2006. doi: [10.1109/TED.2006.884077](https://doi.org/10.1109/TED.2006.884077)

- PTM-MG FinFET nodes:
  > S. Sinha, G. Yeric, V. Chandra, B. Cline and Y. Cao, "Exploring sub-20nm FinFET design with Predictive Technology Models," *DAC 2012*, pp. 283-288. doi: [10.1145/2228360.2228414](https://doi.org/10.1145/2228360.2228414)

<p align="center">
  <a href="./README.zh-CN.md"><img alt="中文 README" src="https://img.shields.io/badge/README-%E4%B8%AD%E6%96%87-blue?style=for-the-badge"></a>
</p>
