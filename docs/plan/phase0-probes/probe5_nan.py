import math
from process_bigraph import Composite, gather_emitter_results
from viva_pulse.core import build_core
from viva_pulse.composites.circuits import pulse_cardiovascular
core = build_core()
sim = Composite({'state': pulse_cardiovascular(core, interval=1.0)}, core=core)
sim.run(60.0)
rows = gather_emitter_results(sim)[('emitter',)]
def leaves(d, p=()):
    if isinstance(d, dict):
        for k, v in d.items(): yield from leaves(v, p + (k,))
    else: yield '/'.join(p), d
ren = [(k, v) for k, v in leaves(rows[-1]) if '/renal/' in k]
bad = [k for k, v in ren if not isinstance(v, (int, float)) or math.isnan(v)]
print('renal leaves', len(ren), 'NaN/non-numeric', len(bad), bad[:4])
kid = dict(ren)
for side in ('left', 'right'):
    print(side, 'kidney pressure at t=0:', round(rows[0] and dict(leaves(rows[0]))['circuits/cardiovascular/renal/%s_kidney/pressure_mmHg' % side], 2),
          ' t=60:', round(kid['circuits/cardiovascular/renal/%s_kidney/pressure_mmHg' % side], 2))
print('rows emitted:', len(rows))
