"""CohortBloodLoss: fraction of blood lost against starting blood volume, one dot per patient.

Written with /viva-viz for the patient-cohort study. Patient names reach a
Visualization only through a declared ``run_labels`` input port, which this class
doesn't declare, so the per-patient MAP traces are a labelled comparative
visualization instead.
"""

import numpy as np
from process_bigraph.visualization import Visualization

from ._figure import CATEGORICAL, SURFACE, axis, layout, missing_runs, render


def _spearman(x, y):
    ranks = lambda values: np.asarray(values).argsort().argsort()
    return float(np.corrcoef(ranks(x), ranks(y))[0, 1])


class CohortBloodLoss(Visualization):
    """Scatter of starting blood volume vs percent lost; hover shows the loss and MAP change."""

    def inputs(self):
        return {
            "blood_volume": "list[list[float]]",
            "hemorrhaged_volume": "list[list[float]]",
            "mean_arterial_pressure": "list[list[float]]",
        }

    @classmethod
    def demo(cls):
        return {
            "blood_volume": [[3683, 2309], [5487, 3936], [6972, 5338], [4177, 2847], [7072, 5340]],
            "hemorrhaged_volume": [[0, 1402], [0, 1577], [0, 1658], [0, 1360], [0, 1755]],
            "mean_arterial_pressure": [[95.2, 70.5], [95.3, 84.1], [95.2, 86.1], [95.1, 78.3],
                                       [100.6, 81.1]],
        }

    def update(self, state):
        error = missing_runs(state, self.inputs())
        if error:
            return error
        start = [run[0] for run in state["blood_volume"]]
        percent = [100.0 * lost[-1] / bv for lost, bv in zip(state["hemorrhaged_volume"], start)]
        custom = [[lost[-1], pressure[0], pressure[-1]] for lost, pressure in
                  zip(state["hemorrhaged_volume"], state["mean_arterial_pressure"])]
        rho = _spearman(start, percent)

        traces = [{
            "x": [bv / 1000.0 for bv in start], "y": percent, "customdata": custom,
            "type": "scatter", "mode": "markers", "name": "patient",
            "marker": {"size": 10, "color": CATEGORICAL[0], "line": {"color": SURFACE, "width": 2}},
            "hovertemplate": ("starting blood volume %{x:.2f} L"
                              "<br>lost %{customdata[0]:.0f} mL (%{y:.1f}%)"
                              "<br>MAP %{customdata[1]:.1f} → %{customdata[2]:.1f} mmHg<extra></extra>"),
        }]
        caption = (f"The same right-leg hemorrhage (severity 0.8, 10 min) in each of the {len(start)} "
                   "patients shipped with Pulse. Hover a dot for the loss and MAP change.")
        figure = layout(
            f"Smaller patients lose a larger share of their blood (Spearman ρ = {rho:.2f})",
            height=480, showlegend=False,
            xaxis=axis("Starting blood volume (L)"),
            yaxis=axis("Blood lost in 10 min (% of starting volume)"),
        )
        return render(self.stable_div_id(), traces, figure, 480, caption)
