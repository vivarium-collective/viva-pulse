# Phase 0 probe report

Scope: the probes in `plan-multiscale-composite.md` that need no biology decision. Probes 2 and 6 (which kidney or cardiomyocyte model) wait on B2 and B5, decided by Arnab or Eran.

Scripts: `docs/plan/phase0-probes/`. Each runs with `-I`. Probe 1 uses a scratch venv with `viva-opencor` (commit `a67510f`) and `viva-copasi` (commit `eed1ca5`, installed, not yet exercised). Probes 3–5 use the viva-pulse `.venv` (process-bigraph 1.11.0, bigraph-schema 1.8.3).

## Results

| # | Probe | Result | Evidence |
|---|---|---|---|
| 1 | `libopencor` installs and runs a real CellML model through `OpenCORProcess` | **Pass** | libopencor 1.20261029.0, arm64. Bundled `van_der_pol.cellml`, 401 output points, state keys `main/x`, `main/y`. |
| 2 | Load a kidney and a cardiomyocyte model | **Deferred** | Waits on B2, B5 |
| 3 | `overwrite[float]` `initial_state` discard on 1.11.0 | **Does not reproduce** | `probe3_init_state.py`: float, overwrite[float], maybe[float] all keep 42.0; boolean keeps True. The repo's delta-seeded design is no longer needed for this bug on 1.11.0, but it is not changed here. |
| 4 | Fast/slow interval lag | **Confirmed, framework only** | `probe4_lag.py`: fast process at 0.1 s, slow at 1.0 s. At t=2 the slow process saw the value at t=1 (10.0), not t=2 (20.0). Not yet run with Pulse. |
| 5 | Renal outputs from Pulse are populated | **Pass** | `probe5_nan.py`: 32/32 renal leaves numeric over 60 s, none NaN. Store path `circuits/cardiovascular/renal/<side>_kidney/<quantity>`. |
| 6 | Model Atlas search for kidney/heart models | **Deferred** | Waits on B2, B5 |

## Open finding

Unperturbed left and right kidney pressure fell from 49.44 mmHg at t=0 to 35.62 mmHg at t=60 s, with no intervention applied. The earlier 3 s run read 43.87 mmHg, so the drop is still in progress at 3 s. Whether this is a settling transient in the loaded state or real baroreflex behavior is not decided. Any Phase 1 result must be compared with a parallel unperturbed baseline run, as the plan already requires.

## Not yet verified

- Probe 4 used toy processes, not Pulse. The lag under a real Pulse process and `OpenCORProcess` is untested.
- Probe 1 ran the bundled Van der Pol model, not a physiological one.
- Probe 5 ran only the whole-body `StandardMale` state.
