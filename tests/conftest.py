import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.core import build_core
from viva_pulse.runtime import PulseNotFoundError, ensure_pulse_importable


def _pulse_available() -> bool:
    """True when a built Pulse install can be found (see viva_pulse.runtime)."""
    try:
        ensure_pulse_importable()
        return True
    except PulseNotFoundError:
        return False


PULSE_AVAILABLE = _pulse_available()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Engine-free CI: skip (don't fail) tests that need the real Pulse build.

    Pulse has no PyPI release — it is a from-source CMake build that CI cannot
    produce — so engine-driving tests raise ``PulseNotFoundError`` when no build
    is present (in a fixture or in the test body). When the engine is absent,
    convert that unhandled error into a skip so the engine-free suite (the
    validation / controller / registry / packaging / docs tests) stays green.
    When a Pulse build IS present (local dev, ``uv run --no-sync pytest``),
    nothing is converted and every engine test runs for real.
    """
    outcome = yield
    if PULSE_AVAILABLE:
        return
    report = outcome.get_result()
    if call.excinfo is not None and call.excinfo.errisinstance(PulseNotFoundError):
        report.outcome = "skipped"
        report.longrepr = (
            str(item.fspath),
            None,
            "Skipped: Kitware Pulse engine not built (engine-free environment); "
            "see README.md to build it.",
        )


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
