"""Check that a Pulse install is complete and that its engine runs.

Usage: verify-pulse-install.py <install-prefix>

Fails unless every state file this repo loads exists, the generated protobuf
code is present, and StandardMale loads and advances 10 s with a finite heart
rate. Uses Pulse's own Python API only, so it can run before viva-pulse is
installed.
"""

import math
import sys
from pathlib import Path

# Every state the tests, studies and docs load (the patient cohort uses all).
STATES = [
    "Bradycardic", "Carol", "Cynthia", "DefaultFemale", "DefaultMale",
    "ExtremeFemale", "ExtremeMale", "Gus", "Hassan", "Jane", "Jeff", "Joel",
    "Nathan", "Overweight", "Rick", "Soldier", "StandardFemale", "StandardMale",
    "Tachycardic", "Underweight", "Ventilated",
]


def main(install: Path) -> int:
    bin_dir, python_dir = install / "bin", install / "python"
    missing = [f"bin/states/{name}@0s.json" for name in STATES
               if not (bin_dir / "states" / f"{name}@0s.json").is_file()]
    if not (bin_dir / "patients" / "StandardMale.json").is_file():
        missing.append("bin/patients/StandardMale.json")
    if not list(bin_dir.glob("PyPulse*.so")):
        missing.append("bin/PyPulse*.so")
    if not list(python_dir.glob("pulse/**/*_pb2.py")):
        missing.append("python/pulse/**/*_pb2.py")
    if missing:
        print("Pulse install is incomplete; missing:", *missing, sep="\n  ", file=sys.stderr)
        return 1

    sys.path[:0] = [str(bin_dir), str(python_dir)]
    import PyPulse
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    if not Path(PyPulse.__file__).resolve().is_relative_to(bin_dir.resolve()):
        print(f"PyPulse imported from {PyPulse.__file__}, not {bin_dir}", file=sys.stderr)
        return 1

    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    request = SEDataRequest.create_physiology_request("HeartRate", unit=scalars.FrequencyUnit.Per_min)
    state = bin_dir / "states" / "StandardMale@0s.json"
    if not engine.serialize_from_file(str(state), SEDataRequestManager([request])):
        print(f"Pulse failed to load {state}", file=sys.stderr)
        return 1
    if not engine.advance_time_s(10.0):
        print("Pulse failed to advance 10 s", file=sys.stderr)
        return 1
    heart_rate = engine.pull_data()[1]
    if not math.isfinite(heart_rate):
        print(f"StandardMale heart rate is {heart_rate} after 10 s", file=sys.stderr)
        return 1
    print(f"Pulse install OK: {len(STATES)} states, StandardMale HR {heart_rate:.2f} bpm after 10 s")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
