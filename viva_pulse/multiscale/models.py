"""Cell models fetched at a pinned version instead of shipped with viva-pulse.

König's kinetic model of human hepatic glucose metabolism (König, Bulik &
Holzhütter 2012, PLoS Comput Biol 8:e1002577) is published as SBML in the
authors' repository, which states no license, so viva-pulse does not ship it.
:func:`koenig_2014` downloads the file once, at a pinned commit, checks its
sha256 and caches it. The BioModels copies (MODEL1204270001, MODEL1209260000)
have no rate laws and cannot be simulated.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

import platformdirs

from ..patients import CACHE_ENV_VAR

KOENIG_2014_URL = ("https://raw.githubusercontent.com/matthiaskoenig/glucose-liver/"
                   "78c577de137eb3405d07b216f610c33f73f5c883/sbml/"
                   "Koenig2014_Hepatic_Glucose_Model_annotated.xml")
KOENIG_2014_SHA256 = "177297ad8aa8e0e23103c8322dc9249a28a68bb0dc915d533694a9cfa8608b8e"


def models_dir() -> Path:
    """``models/`` under ``$VIVA_PULSE_CACHE_DIR`` if set, else under the user cache directory."""
    override = os.environ.get(CACHE_ENV_VAR)
    root = Path(override).expanduser().resolve() if override else platformdirs.user_cache_path("viva-pulse")
    return root / "models"


def koenig_2014() -> Path:
    """Path of König's hepatic glucose model, downloaded on first use.

    The bytes must match the pinned sha256, before and after caching: a mismatch
    raises instead of running a different model.
    """
    path = models_dir() / f"Koenig2014_Hepatic_Glucose_Model-{KOENIG_2014_SHA256[:12]}.xml"
    if path.exists():
        _check(path.read_bytes(), path)
        return path
    with urllib.request.urlopen(KOENIG_2014_URL, timeout=60) as response:
        data = response.read()
    _check(data, KOENIG_2014_URL)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
    os.replace(tmp.name, path)
    return path


def _check(data: bytes, source) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != KOENIG_2014_SHA256:
        raise ValueError(f"König 2014 model from {source} has sha256 {digest}, expected {KOENIG_2014_SHA256}")


#: Named parameter sets for König's model, applied per subpopulation.
#: - ``published``: the file as published.
#: - ``provisional_corrections``: three equilibrium constants corrected against
#:   eQuilibrator (docs/plan/cell-content-probes, probes C-D). Provisional, not a
#:   modeler's decision. ``EN_keq`` was copied from ``TPI_keq`` (eQuilibrator K' at
#:   pH 7.2, pMg 3, I 0.25 M, 310.18 K); ``LDH_keq`` is the reverse-direction constant
#:   (inverted); ``ALD_keq`` is declared mM but matches K' in M (x1000). It makes the
#:   thermodynamics consistent but the liver then makes no glucose at fasting
#:   levels: the published calibration leans on the original values.
KOENIG_PARAMETER_SETS = {
    "published": {},
    "provisional_corrections": {
        "EN_keq": 4.346,
        "LDH_keq": 1 / 0.000278321076004752,
        "ALD_keq": 9.76298897362969e-5 * 1000,
    },
}
