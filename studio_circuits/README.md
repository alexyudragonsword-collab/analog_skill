# studio_circuits — original Analog Studio sizing circuits

Circuits authored for the Analog Studio **Sizing** tab, *not* vendored from an
upstream project. They are released under the app's MIT LICENSE.

They deliberately reuse the AnalogGym characterization contract so they slot
into the same evaluate→score→optimize pipeline as the vendored AnalogGym
amplifiers:

- a `.subckt <name> gnda vdda vinn vinp vout` on the open SKY130 PDK
  (`sky130_fd_pr__{nfet,pfet}_01v8`), self-biased from one internal reference
  current source (no external bias pins);
- a `.PARAM` variables file (`W_* L_* M_*`, bias current) parsed into the
  editable sizing variables;
- the shared `TB_Amplifier_ACDC.cir` testbench, which yields the full 9-metric
  report (DC gain, GBW, phase margin, PSRR±, CMRR, power, offset, temp-coeff).

`amp/testbench/TB_Amplifier_ACDC.cir` is a verbatim copy of the AnalogGym
testbench (BSD-3-Clause, CODA-Team) so the harness is byte-identical; see the
top-level `analoggym/` tree and NOTICE for its license.

## Circuits

| file | topology | notes |
|------|----------|-------|
| `amp/{netlist,variables}/CM_OTA_Pin_3` | PMOS-input current-mirror (symmetric) OTA | single-stage, self-biased, single-ended; genuine gain ↔ GBW ↔ power trade-off on a 500 pF load |

The current-mirror OTA is single-stage, so every internal node is
diode-connected and self-biasing — it converges robustly across the whole
sizing box (unlike a cascode topology that needs delicate external bias
voltages). Default sizing: DC gain ≈ 42 dB, GBW ≈ 0.37 MHz, PM ≈ 90°,
power ≈ 0.42 mW.
