from process_bigraph import Process, Composite, allocate_core
import importlib.metadata as m
print('process-bigraph', m.version('process-bigraph'))

class Fast(Process):
    # emits +1 per update of 0.1 s, so the store equals t/0.1 once up to date
    def inputs(self): return {}
    def outputs(self): return {'count': 'float'}
    def initial_state(self): return {'count': 0.0}
    def update(self, s, interval): return {'count': 1.0}

class Slow(Process):
    # reads the fast counter at the start of its 1.0 s interval; records what it saw
    def inputs(self): return {'count': 'float'}
    def outputs(self): return {'seen': 'overwrite[float]'}
    def initial_state(self): return {'seen': 0.0}
    def update(self, s, interval): return {'seen': s['count']}

core = allocate_core(); core.register_link('Fast', Fast); core.register_link('Slow', Slow)
doc = {'state': {
    'fast': {'_type': 'process', 'address': 'local:Fast', 'interval': 0.1,
             'outputs': {'count': ['c']}},
    'slow': {'_type': 'process', 'address': 'local:Slow', 'interval': 1.0,
             'inputs': {'count': ['c']}, 'outputs': {'seen': ['seen']}}}}
sim = Composite(doc, core=core)
for t in range(1, 4):
    sim.run(1.0)
    print('t=%.1f  store count=%s  slow saw=%s' % (t, sim.state['c'], sim.state['seen']))
