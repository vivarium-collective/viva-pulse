"""Cell models fetched at a pinned version (network: GitHub raw)."""

import hashlib

import pytest

from viva_pulse.multiscale.models import KOENIG_2014_SHA256, koenig_2014


def test_koenig_is_fetched_once_and_checked(tmp_path, monkeypatch):
    """Falsifies: the fetched file isn't the pinned one, or a tampered cache is used.
    Second call must read the cache (same path) and still verify it."""
    monkeypatch.setenv("VIVA_PULSE_CACHE_DIR", str(tmp_path))
    path = koenig_2014()
    assert path.is_relative_to(tmp_path / "models")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == KOENIG_2014_SHA256
    assert koenig_2014() == path
    path.write_bytes(path.read_bytes() + b"<!-- changed -->")
    with pytest.raises(ValueError, match="sha256"):
        koenig_2014()
