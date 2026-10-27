# Installation

Pulse has no PyPI release, so it is built from source, and viva-pulse runs in the virtual
environment that build targets.

## Requirements

- A Pulse source checkout at `../engine`, pinned to engine commit `5e29e5b13` (Pulse 4.4.0).
- CMake 3.31 or newer, a C++20 compiler, and a JDK (Pulse's data generation uses Java).
- [uv](https://docs.astral.sh/uv/) and CPython 3.12. `PyPulse` must be compiled against the
  same Python that runs viva-pulse.

## Build Pulse and install viva-pulse

From the viva-pulse repository root:

```bash
uv venv --seed --python 3.12 .venv      # --seed: the Pulse build pip-installs protobuf into this venv

# Configure and build Pulse into .pulse-build/install (gitignored). Takes a while the first time.
VIRTUAL_ENV=$PWD/.venv cmake --fresh -S ../engine -B .pulse-build \
  -DCMAKE_BUILD_TYPE:STRING=Release -DPulse_PYTHON_HOME_DIR=$PWD/.venv \
  -DPython3_FIND_VIRTUALENV=ONLY \
  -DPulse_JAVA_API=ON -DPulse_PYTHON_API=ON -DPulse_GEN_DATA=ON
VIRTUAL_ENV=$PWD/.venv cmake --build .pulse-build -j 12

uv pip install -r ../engine/requirements.txt
uv pip install -e '.[dev]'
```

Pulse's CMake ignores `-DPython3_EXECUTABLE`; it selects the venv through
`-DPulse_PYTHON_HOME_DIR` together with `VIRTUAL_ENV`. Build pins and known workarounds are in
the repository's `.build-progress.md`.

:::{warning}
**Never run `uv sync`.** The venv is assembled by hand. A sync would write a lock file and
remove the dev extra and the engine requirements. Run everything with
`uv run --no-sync`.
:::

## Where viva-pulse looks for Pulse

`viva_pulse.runtime` uses the first of these that is set:

1. the `install_dir` config of a process;
2. the `PULSE_INSTALL_DIR` environment variable;
3. `.pulse-build/install` in the repository.

A location given explicitly that is not a valid install raises `PulseNotFoundError`; it never
falls back to another location. See {doc}`api/runtime`.

## Optional parts

- **The workbench.** `vivarium-workbench` is in the `workbench` extra, with what the studies,
  figures and reports use. It is pinned to a `main` commit in `pyproject.toml`, and the `dev`
  extra includes it, so `uv pip install -e '.[dev]'` installs it. The library (the processes
  and composites) needs none of it: a project using viva-pulse as a dependency installs viva-pulse
  without extras. Serve the workbench from this venv:
  see {doc}`howto/run-studies-in-the-workbench`.
- **These docs.** `uv pip install --group docs`, then `make docs` builds them, running every
  tutorial against the engine, and opens them in your browser.

## Check the install

```bash
uv run --no-sync pytest -q          # the full real-engine suite, about four minutes
```
