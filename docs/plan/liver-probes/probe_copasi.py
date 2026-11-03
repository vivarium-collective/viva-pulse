import sys, time
from viva_pulse.runtime import ensure_pulse_importable
ensure_pulse_importable()
import pulse.engine.PulseEngine  # noqa: F401  PyPulse and COPASI in one process
from process_bigraph import allocate_core
from viva_copasi.processes import CopasiUTCProcess
from viva_pulse.multiscale import KOSCHORRECK_2008
src = sys.argv[1] if len(sys.argv) > 1 else str(KOSCHORRECK_2008)
core = allocate_core()
p = CopasiUTCProcess({'model_source': src, 'time': 1.0, 'intervals': 1}, core=core)
state = p.initial_state()['species_concentrations']
print('initial', {k: round(v, 4) for k, v in state.items()})
t0 = time.perf_counter(); marks = {1, 60, 600, 1800, 3600, 7200}
for t in range(1, 7201):
    upd = p.update({'species_counts': {'ins': 0.16}, 'species_concentrations': state}, 1.0)['species_concentrations']
    state = {k: state[k] + upd[k] for k in state}
    if t in marks:
        print(f't={t:5d}', {k: round(state[k], 4) for k in ('R', 'IR', 'I2R', 'IRp', 'I2Rp', 'Ren', 'IRen')})
el = time.perf_counter() - t0
print(f'{el/7200*1e3:.2f} ms per 1 s update')
