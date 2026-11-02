# Run studies in the workbench

viva-pulse is a [vivarium-workbench](https://github.com/vivarium-collective/vivarium-workbench)
workspace (`workspace.yaml` at the repository root), so its composite generators appear in the
workbench's catalog and can be run as **studies**: a baseline composite, variants of it, a
record of every run, and pass criteria. An **investigation** groups studies under one question.
This page shows how the `pulse-hemorrhage` investigation is set up and run; its results are on
{doc}`../results/pulse-hemorrhage`.

## Serve the workbench from the project's venv

The workbench runs every simulation in the Python environment of the process serving it, and
only this project's `.venv` can import PyPulse. So serve it from there:

```bash
.venv/bin/vwb serve --detach          # prints the dashboard URL
.venv/bin/vwb server-status           # running / stale / stopped
```

State lives in `.pbg/server/` (gitignored). A globally installed `vwb` can't run these
composites. After changing a figure class in `viva_pulse/visualizations/`, restart the server
(`.venv/bin/vwb server-restart`): its worker caches imported classes.

## How a study is laid out

Studies live in `workspace/studies/<slug>/`:

- `study.yaml`: the question, the baseline and variants, the readouts to record, the findings.
- `tests/`: pytest files with the pass criteria, run by the workbench.
- `runs.db`: the record of every run (committed).

Each **baseline** names a composite generator and its parameters. Each **variant** overrides
some of them. A variant may also name its own generator, as the treated arms of
`fluid-resuscitation` do:

```yaml
baseline:
- name: untreated
  composite: viva_pulse.composites.hemorrhage.pulse_hemorrhage
  params: {state_file: StandardMale@0s.json, compartment: RightLeg, severity: 0.8, n_steps: 600}
variants:
- name: blood-map-90
  composite: viva_pulse.composites.hemorrhage.pulse_resuscitation
  parameter_overrides: {compound: Blood, target_map_mmHg: 90.0, n_steps: 600, ...}
```

Create studies and their entries through the workbench API (or the `/viva-study` skill), for
example `POST /api/study-create`, `/api/study-baseline-add` and `/api/study-variant-add`.

- **A sweep is one variant per value.** The workbench runs `kind: sweep` only through its
  v2ecoli workflow, so `hemorrhage-severity-sweep` has one variant per severity and
  `patient-cohort` one per patient state file.
- **Set the run length.** Each baseline carries `n_steps: 600` in its params; without it the
  investigation runner falls back to 5 steps.
- **Only readouts are recorded.** A run stores the `readouts[].store_path` values at every
  step, so list everything the criteria and figures need.

## Run the investigation

```bash
URL=$(jq -r .url .pbg/server/server-info)
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"investigation": "pulse-hemorrhage"}' $URL/api/investigation-run-unblocked
```

This queues each study's first baseline and every variant (30 runs, about ten minutes), then
renders the studies' comparative figures. Poll
`$URL/api/investigation-run-unblocked-status?job_id=<id>` for progress.

## Check the criteria

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"study": "patient-cohort"}' $URL/api/study-tests-run
```

Or, without the server: `uv run --no-sync pytest -q workspace/studies/patient-cohort/tests`.
The tests read the study's `runs.db` through `vivarium_workbench.testing.Run`. A shared
fixture checks, before any criterion runs, that each label's newest run completed, ran with the
parameters the study declares, came from the same commit as the others, and never reached an
irreversible state.

## Inspect the record

Every run is a row in `runs_meta` (parameters, git commit, Python version) with its readouts
in `history`:

```python
from vivarium_workbench.testing import Run
run = Run("workspace/studies/patient-cohort/runs.db")      # the latest run
run.label, run.params, run.final("vitals.mean_arterial_pressure_mmHg")
```

## Known workbench limits

- The workbench's computed verdicts read only YAML behavior tests. The study detail page
  counts the pytest results from the last `/api/study-tests-run` (not from a plain pytest
  run), but the investigation page, its report and the needs-attention panel show the
  studies as blocked, and the investigation's computed verdict as in progress.

The bespoke figures don't declare the workbench's `run_labels` port, so labelled time
courses are the studies' `comparative_visualizations`. With the pinned workbench,
`check-observables`, and the report lint when run against the server, accept every
`vitals.*` readout; older pins flagged them.
