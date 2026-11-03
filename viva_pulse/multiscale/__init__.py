"""Lower scales under Pulse: a stratified liver tissue block of COPASI cell models.

The cell process needs the ``multiscale`` extra (viva-copasi); the rest of the
package imports without it. See ``docs/plan/plan-multicell-composition.md``,
Design 1.
"""

from .tissue import (KOSCHORRECK_2008, HepaticGradient, HepaticReplay, TissueAggregate, hepatic_trajectory,
                     save_hepatic_trajectory)


def register_multiscale(core):
    """Register the COPASI cell process (the tissue steps are in ``build_core()``).

    Raises ImportError without the ``multiscale`` extra.
    """
    try:
        from .cells import EquilibratedCopasiProcess
    except ImportError as error:
        raise ImportError("the tissue block needs COPASI: install viva-pulse's `multiscale` extra "
                          "(see README.md)") from error
    core.register_link("EquilibratedCopasiProcess", EquilibratedCopasiProcess)
    return core


__all__ = ["KOSCHORRECK_2008", "HepaticGradient", "HepaticReplay", "TissueAggregate", "hepatic_trajectory",
           "register_multiscale", "save_hepatic_trajectory"]
