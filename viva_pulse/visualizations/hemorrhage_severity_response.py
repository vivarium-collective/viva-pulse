"""HemorrhageSeverityResponse: final vitals against bleed severity, plus MAP over time.

Written with /viva:viz for the hemorrhage-severity-sweep study.
"""

from process_bigraph.visualization import Visualization

from ._figure import AXIS, CATEGORICAL, MUTED, ORDINAL_BLUE, axis, layout, missing_runs, render

_DEMO_SEVERITIES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def _demo(fn):
    return [[fn(s, t) for t in range(0, 601, 120)] for s in _DEMO_SEVERITIES]


class HemorrhageSeverityResponse(Visualization):
    """Small multiples of final blood loss, heart rate and MAP vs severity, and MAP vs time."""

    def inputs(self):
        return {
            "time": "list[list[float]]",
            "severity": "list[list[float]]",
            "mean_arterial_pressure": "list[list[float]]",
            "heart_rate": "list[list[float]]",
            "hemorrhaged_volume": "list[list[float]]",
        }

    @classmethod
    def demo(cls):
        return {
            "time": _demo(lambda s, t: float(t)),
            "severity": _demo(lambda s, t: s),
            "mean_arterial_pressure": _demo(lambda s, t: 95.3 - 14 * max(0.0, s - 0.5) * t / 600),
            "heart_rate": _demo(lambda s, t: 72 + 45 * s * t / 600),
            "hemorrhaged_volume": _demo(lambda s, t: 1800 * s * t / 600),
        }

    def update(self, state):
        error = missing_runs(state, self.inputs())
        if error:
            return error
        runs = sorted(zip(state["severity"], state["time"], state["mean_arterial_pressure"],
                          state["heart_rate"], state["hemorrhaged_volume"]),
                      key=lambda run: run[0][-1])
        severity = [run[0][-1] for run in runs]
        finals = {
            "lost": [run[4][-1] for run in runs],
            "hr": [run[3][-1] for run in runs],
            "map": [run[2][-1] for run in runs],
        }
        start_map = runs[0][2][0]

        traces = []
        panels = [("lost", "Blood lost (mL)", "x", "y"),
                  ("hr", "Heart rate (1/min)", "x2", "y2"),
                  ("map", "MAP (mmHg)", "x3", "y3")]
        for key, title, xa, ya in panels:
            traces.append({
                "x": severity, "y": finals[key], "xaxis": xa, "yaxis": ya,
                "type": "scatter", "mode": "lines+markers", "name": title, "showlegend": False,
                "line": {"color": CATEGORICAL[0], "width": 2}, "marker": {"size": 8},
                "hovertemplate": f"severity %{{x}}<br>{title} at 10 min: %{{y:.1f}}<extra></extra>",
            })

        bleeding = [run for run in runs if run[0][-1] > 0.0]
        colors = ORDINAL_BLUE[-len(bleeding):] if bleeding else []
        for run in runs:
            level = run[0][-1]
            color = MUTED if level == 0.0 else colors[bleeding.index(run)]
            traces.append({
                "x": [t / 60.0 for t in run[1]], "y": run[2], "xaxis": "x4", "yaxis": "y4",
                "type": "scatter", "mode": "lines", "name": f"severity {level:g}",
                "line": {"color": color, "width": 2, "dash": "dash" if level == 0.0 else "solid"},
                "hovertemplate": f"severity {level:g}<br>%{{x:.1f}} min: %{{y:.1f}} mmHg<extra></extra>",
            })

        band = {"type": "rect", "xref": "x3 domain", "yref": "y3", "x0": 0, "x1": 1,
                "y0": start_map - 2, "y1": start_map + 2, "fillcolor": AXIS, "opacity": 0.35,
                "line": {"width": 0}, "layer": "below"}
        caption = ("Right-leg hemorrhage, StandardMale, 10 min per run. Top: values at 10 min against "
                   "severity; the gray band is the starting MAP ±2 mmHg. Bottom: MAP over time "
                   "(dashed gray = no bleed).")
        figure = layout(
            "MAP holds for mild bleeds, then falls once compensation is outrun",
            height=700, shapes=[band],
            legend={"orientation": "h", "y": -0.2, "font": {"size": 11}},
            xaxis=axis("Severity", domain=[0.0, 0.28], anchor="y"),
            xaxis2=axis("Severity", domain=[0.36, 0.64], anchor="y2"),
            xaxis3=axis("Severity", domain=[0.72, 1.0], anchor="y3"),
            xaxis4=axis("Time (min)", domain=[0.0, 1.0], anchor="y4"),
            yaxis=axis("Blood lost (mL)", domain=[0.6, 1.0], anchor="x"),
            yaxis2=axis("Heart rate (1/min)", domain=[0.6, 1.0], anchor="x2"),
            yaxis3=axis("MAP (mmHg)", domain=[0.6, 1.0], anchor="x3"),
            yaxis4=axis("MAP (mmHg)", domain=[0.0, 0.42], anchor="x4"),
        )
        return render(self.stable_div_id(), traces, figure, 700, caption)
