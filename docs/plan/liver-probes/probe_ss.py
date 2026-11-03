import sys

import viva_pulse.multiscale.cells  # noqa: F401  imports COPASI with the locale kept
from basico import load_model, set_species, run_steadystate, get_species
from viva_pulse.multiscale import KOSCHORRECK_2008
dm = load_model(sys.argv[1] if len(sys.argv) > 1 else str(KOSCHORRECK_2008))
set_species(name='ins', exact=True, initial_concentration=0.16, model=dm)
r = run_steadystate(model=dm, update_model=True)
print('steadystate return', r)
sp = get_species(model=dm)
print({n: round(float(sp.loc[n, 'concentration']), 4) for n in ('R', 'IR', 'I2R', 'IRp', 'I2Rp', 'Ren', 'IRen')})
print({n: round(float(sp.loc[n, 'initial_concentration']), 4) for n in ('R', 'IR', 'IRp', 'Ren')})
