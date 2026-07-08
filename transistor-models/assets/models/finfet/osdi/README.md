# BSIM-CMG OSDI model for FinFET support

FinFET nodes use BSIM-CMG (Verilog-A level 72), which stock ngspice does not
compile in. We load it at runtime through ngspice's OSDI interface
(`pre_osdi`), from a precompiled `bsimcmg.osdi`.

## Files
- `linux_amd64/bsimcmg.osdi` — compiled for Linux x86-64 (ngspice OSDI 0.3).
- `va_src/` — the BSIM-CMG 112.0.0 Verilog-A source (module `bsimcmg_va`),
  plus its LICENSE/NOTICE. Kept for reproducibility and to build other
  platforms.

## Rebuilding (e.g. for Windows)
Download the OpenVAF compiler for the target platform, then:

    openvaf bsimcmg.va      # → bsimcmg.osdi

Drop the result under `osdi/<platform>/bsimcmg.osdi`. The app auto-detects the
per-platform file; FinFET features stay disabled if none is present or the
user's ngspice lacks OSDI support.

## Provenance
- BSIM-CMG 112.0.0 — © UC Berkeley (see va_src/LICENSE.txt, NOTICE.txt).
- PTM-MG modelcards (`../hp`, `../lstp`) — © ASU PTM (academic use).
