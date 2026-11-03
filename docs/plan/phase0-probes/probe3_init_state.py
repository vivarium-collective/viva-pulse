from process_bigraph import Process, Composite, allocate_core
for typ in ('float', 'overwrite[float]', 'maybe[float]', 'boolean'):
    val = True if typ == 'boolean' else 42.0
    class P(Process):
        def inputs(self): return {}
        def outputs(self): return {'x': typ}
        def initial_state(self): return {'x': val}
        def update(self, s, i): return {}
    core = allocate_core(); core.register_link('P', P)
    sim = Composite({'state': {'p': {'_type': 'process', 'address': 'local:P',
                                     'outputs': {'x': ['s', 'x']}}}}, core=core)
    print(typ, sim.state['s'])
