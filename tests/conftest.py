import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.core import build_core


@pytest.fixture
def run_composite():
    """Build a generator's document on a fresh core, run it, return (sim, rows)."""

    def _run(generator, duration, **params):
        core = build_core()
        sim = Composite({"state": generator(core, **params)}, core=core)
        sim.run(duration)
        return sim, gather_emitter_results(sim)[("emitter",)]

    return _run


@pytest.fixture
def assert_rows_close():
    """Compare emitted rows (nested dicts of readings) to 1e-9 relative. Identical Pulse runs
    in one process aren't always bit-identical: 1 in 40 identical runs differed by 4.4e-14
    relative, which made exact-equality tests fail intermittently."""

    def _close(rows, expected, rel=1e-9):
        def close(a, b):
            if isinstance(a, dict):
                assert a.keys() == b.keys()
                for key in a:
                    close(a[key], b[key])
            elif isinstance(a, float):
                assert a == pytest.approx(b, rel=rel, abs=1e-12)
            else:
                assert a == b

        assert len(rows) == len(expected)
        for row, row_expected in zip(rows, expected):
            close(row, row_expected)

    return _close
