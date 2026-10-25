"""Save Pulse engine states during a run, one state file per requested simulation time.

A saved state is an ordinary Pulse state file: ``state_file`` loads it as the start of
another run (``PulseProcess``, ``PulseCircuitProcess``), so a run can be checkpointed at
``t`` and branched under several interventions. Pulse records the whole engine in it,
including paths and active actions added during the run (a hemorrhage's bleed path and
link are in it, and the bleed continues after reload), and its ``SimulationTime``.

A reloaded state continues the run closely but not bit-identically: saved at 10 s and
advanced 20 s, every vital agrees with the uninterrupted run to 2e-8 relative (probe
``save-states-2026-10-25``).

Files are named ``<name>@<t>s.json``, Pulse's own convention for its shipped states, with
``t`` the engine's simulation time rounded to the microsecond (Pulse advances in 0.02 s
steps, so 10 s is reached as 9.999999999999876). An existing file is never overwritten.

Only whole-body engines can be saved: Pulse doesn't serialize VentilationMechanics.
``save_states`` drives the engine it is given. It is for an engine you hold (Pulse's API,
the command line); the engine inside a ``PulseProcess`` or ``PulseCircuitProcess`` belongs to
the running composite, which advances it itself.

Command line, from a state file Pulse ships (a bare name) or a path::

    python -m viva_pulse.states StandardMale@0s.json --times 60 120 --out states/
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Sequence

#: Saved-state names use the engine's time rounded to this many decimals (1 µs).
TIME_DECIMALS = 6


def _seconds(t: float) -> str:
    """``t`` in fixed point at TIME_DECIMALS, without trailing zeros: 10, 2.5, 86400.02."""
    return f"{t:.{TIME_DECIMALS}f}".rstrip("0").rstrip(".")


def save_states(engine, out_dir: str | Path, times_s: Sequence[float], name: str = "state") -> list[Path]:
    """Advance ``engine`` to each simulation time in ``times_s`` and save its state there.

    ``engine`` is a loaded whole-body ``pulse.engine.PulseEngine`` (a state file, an edited
    state, a stabilized patient); any other raises before it is advanced. ``times_s`` are
    absolute simulation times, in increasing order and not before the engine's current
    time. Each state is saved at the first Pulse step (0.02 s) at or after its time, so two
    times within one step raise; a time equal to the current one saves without advancing.
    An existing file raises instead of being overwritten. Returns the written paths, in
    order. Raises if Pulse fails to advance (for example an irreversible state) or to save;
    files written before the failure stay.
    """
    import PyPulse

    if isinstance(times_s, (int, float)):
        raise ValueError(f"times_s must be a sequence of times, got the number {times_s}")
    if not name or "/" in name or "@" in name:
        raise ValueError(f"name must be non-empty, without '/' or '@', got {name!r}")
    times = [float(t) for t in times_s]
    if not times:
        raise ValueError("times_s is empty")
    if not all(math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"times_s must be finite and strictly increasing, got {list(times_s)}")
    if not engine.serialize_to_string(PyPulse.serialization_format.json):
        raise ValueError("Pulse can't save this engine's state (only whole-body engines serialize; "
                         "VentilationMechanics doesn't)")
    engine.advance_time_s(0.0)  # pulls, so pull_data()[0] is the current simulation time
    now = engine.pull_data()[0]
    if round(times[0], TIME_DECIMALS) < round(now, TIME_DECIMALS):
        raise ValueError(f"times_s starts at {times[0]} s, before the engine's time {now} s")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in times:
        # One Pulse step at a time: advance_time_s takes int(duration / dt) steps, and a
        # duration computed as t - now is one step short whenever now has drifted just above a
        # step (advance_time_s(4 - 3.000000000000002) ends at 3.98).
        while round(now, TIME_DECIMALS) < round(t, TIME_DECIMALS):
            if not engine.advance_time():
                raise RuntimeError(f"Pulse failed to advance to {t} s (engine at {now} s)")
            now = engine.pull_data()[0]
        path = out / f"{name}@{_seconds(now)}s.json"
        if path in paths:
            raise ValueError(f"times {t} s and an earlier one both fall on Pulse's step at {now} s")
        if path.exists():
            raise FileExistsError(f"{path} exists; save_states never overwrites a state")
        if not engine.serialize_to_file(str(path)):
            raise RuntimeError(f"Pulse failed to save its state at {now} s to {path}")
        paths.append(path)
    return paths


def main(argv: Sequence[str] | None = None) -> list[Path]:
    """Load a state file and save the engine's state at each requested time."""
    from .processes import _load_engine

    parser = argparse.ArgumentParser(prog="python -m viva_pulse.states", description=main.__doc__)
    parser.add_argument("state_file", help="a bare name is a state in <install>/bin/states/; "
                                           "anything with a path separator is a path")
    parser.add_argument("--times", type=float, nargs="+", required=True,
                        help="absolute simulation times to save at, in seconds, increasing")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--name", default=None,
                        help="file name stem (default: the state file's, before '@')")
    parser.add_argument("--install-dir", default="", help="Pulse install prefix")
    args = parser.parse_args(argv)

    state = args.state_file
    if Path(state).name != state:  # a path, relative to the working directory
        state = str(Path(state).expanduser().resolve())
    engine = _load_engine(args.install_dir, "HumanAdultWholeBody", state, [])
    name = args.name or Path(args.state_file).stem.split("@")[0]
    paths = save_states(engine, args.out, args.times, name)
    for path in paths:
        print(path)
    return paths


if __name__ == "__main__":
    main()
