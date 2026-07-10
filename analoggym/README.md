# Vendored AnalogGym subset (sizing benchmark assets)

Source: [CODA-Team/AnalogGym](https://github.com/CODA-Team/AnalogGym)
(commit `0a9d139`, 2025-10-29) — "AnalogGym: An Open and Practical Testing
Suite for Analog Circuit Synthesis", ICCAD 2024 (arXiv 2409.08534).
License: **BSD 3-Clause** (see `LICENSE` in this directory); copyright
(c) 2024, CODA-Team.

This is the **open-source subset only** (ngspice + SkyWater SKY130):

```
amp/netlist/     17 Miller multi-stage op-amp subckts (SKY130)
amp/variables/   matching .PARAM design-variable files
amp/testbench/   TB_Amplifier_ACDC.cir / TB_Amplifier_Tran.cir
amp/schematic/   schematic PNG for the circuit(s) wired into the GUI
ldo/…                  Basic LDO + 4 variants (netlists, variables,
                       dev-params probes, per-variant testbenches)
pdk/sky130_pdk.zip     SKY130 ngspice model files (extracted to the
                       user workspace on first use, ~109 MB unpacked)
```

Used by Analog Studio's **Sizing tab** (`app/core/sizing.py`): the
testbenches are re-rendered with workspace paths at run time; nothing in
this tree is modified. The DUT contract is the AnalogGym 5-pin
(amplifier: `gnda vdda vinn vinp vout`) / 7-pin (LDO) subckt interface.

Not registered in the GUI due to upstream defects: Qu_LEC (empty
netlist) and Tan_CLIA (default width below the SKY130 model-bin
range). Requires ngspice ≥ 42 (per upstream README, ngspice 41 mis-handles the
temperature/current DC sweeps used by the testbenches).

Analysis of the upstream repository: see `../ANALOG_REPOS_ANALYSIS.md`.
