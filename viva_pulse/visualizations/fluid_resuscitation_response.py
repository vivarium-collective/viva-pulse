"""FluidResuscitationResponse: MAP, blood volume and commanded infusion over
time for the three resuscitation arms.

The three runs reach this figure without their arm names — a run's identity does
not reach a Visualization. We separate them by signal instead: the arm whose
commanded infusion never leaves zero is the untreated control; the other two are
the treated arms (saline and whole blood), which the study finds indistinguishable
over ten minutes, so they are drawn in one colour and overlap on purpose. A
marker on the infusion panel shows where the closed loop first engages.

Written for the fluid-resuscitation study.
"""

from process_bigraph.visualization import Visualization

from ._figure import AXIS, CATEGORICAL, MUTED, TEXT_SECONDARY, axis, layout, missing_runs, render

_TREATED = "Treated (saline / whole blood)"
_UNTREATED = "Untreated"


class FluidResuscitationResponse(Visualization):
    """MAP, blood volume and commanded infusion over time, untreated vs the two
    treated arms, with the moment the MAP controller engages."""

    def inputs(self):
        return {
            "time": "list[list[float]]",
            "mean_arterial_pressure": "list[list[float]]",
            "blood_volume": "list[list[float]]",
            "iv_rate": "list[list[float]]",
        }

    @classmethod
    def demo(cls):
        t = list(range(0, 601, 20))

        def arm(treated):
            engage = 508
            mp, bv, iv = [], [], []
            for x in t:
                relief = 3.4 * max(0.0, min(1.0, (x - engage) / 92.0)) if treated else 0.0
                vol = 80.0 * max(0.0, min(1.0, (x - engage) / 92.0)) if treated else 0.0
                mp.append(95.3 - 11.0 * min(1.0, x / 520.0) + relief)
                bv.append(5000.0 - 1100.0 * min(1.0, x / 520.0) + vol)
                iv.append(25.0 if treated and x >= engage else 0.0)
            return mp, bv, iv

        arms = [arm(False), arm(True), arm(True)]
        return {
            "time": [list(t) for _ in arms],
            "mean_arterial_pressure": [a[0] for a in arms],
            "blood_volume": [a[1] for a in arms],
            "iv_rate": [a[2] for a in arms],
        }

    def update(self, state):
        error = missing_runs(state, self.inputs())
        if error:
            return error

        runs = list(zip(state["time"], state["mean_arterial_pressure"],
                        state["blood_volume"], state["iv_rate"]))
        # Draw the untreated control first (behind), then the treated arms.
        runs.sort(key=lambda run: max(run[3]) > 0.0)

        panels = [
            (1, "mean_arterial_pressure", "x", "y", "MAP (mmHg)"),
            (2, "blood_volume", "x2", "y2", "Blood volume (mL)"),
            (3, "iv_rate", "x3", "y3", "Infusion (mL/min)"),
        ]
        series_index = {"mean_arterial_pressure": 1, "blood_volume": 2, "iv_rate": 3}

        traces = []
        shown = set()
        engaged_min = None
        for run in runs:
            treated = max(run[3]) > 0.0
            name = _TREATED if treated else _UNTREATED
            color = CATEGORICAL[0] if treated else MUTED
            dash = "solid" if treated else "dash"
            t_min = [t / 60.0 for t in run[0]]
            if treated and engaged_min is None:
                for t, rate in zip(run[0], run[3]):
                    if rate > 0.0:
                        engaged_min = t / 60.0
                        break
            for _, key, xa, ya, _label in panels:
                show = name not in shown and xa == "x"
                if show:
                    shown.add(name)
                traces.append({
                    "x": t_min, "y": run[series_index[key]], "xaxis": xa, "yaxis": ya,
                    "type": "scatter", "mode": "lines", "name": name,
                    "legendgroup": name, "showlegend": show,
                    "line": {"color": color, "width": 2, "dash": dash},
                    "hovertemplate": f"{name}<br>%{{x:.1f}} min: %{{y:.1f}}<extra></extra>",
                })

        shapes, annotations = [], []
        if engaged_min is not None:
            for ya in ("y", "y2", "y3"):
                xref = "x" if ya == "y" else f"x{ya[1:]}"
                shapes.append({"type": "line", "xref": xref, "yref": f"{ya} domain",
                               "x0": engaged_min, "x1": engaged_min, "y0": 0, "y1": 1,
                               "line": {"color": CATEGORICAL[1], "width": 1.5, "dash": "dot"},
                               "layer": "below"})
            annotations.append({"xref": "x3", "yref": "y3 domain", "x": engaged_min, "y": 1.0,
                                "text": f"controller engages ~{engaged_min:.1f} min",
                                "showarrow": False, "xanchor": "left", "yshift": 6, "xshift": 4,
                                "font": {"size": 11, "color": CATEGORICAL[1]}})

        caption = ("Severe right-leg hemorrhage, StandardMale, 10 min. The untreated control "
                   "(gray, dashed) keeps bleeding; the two treated arms (blue) overlap — saline "
                   "and whole blood are indistinguishable over this window. The closed loop only "
                   "infuses once MAP falls below its 90 mmHg target, late in the run.")
        figure = layout(
            "Closed-loop infusion arrests the fall in pressure; compound does not matter in 10 min",
            height=720, shapes=shapes, annotations=annotations,
            legend={"orientation": "h", "y": -0.12, "font": {"size": 11}},
            xaxis=axis("", domain=[0.0, 1.0], anchor="y", matches="x3", showticklabels=False),
            xaxis2=axis("", domain=[0.0, 1.0], anchor="y2", matches="x3", showticklabels=False),
            xaxis3=axis("Time (min)", domain=[0.0, 1.0], anchor="y3"),
            yaxis=axis("MAP (mmHg)", domain=[0.70, 1.0], anchor="x"),
            yaxis2=axis("Blood volume (mL)", domain=[0.37, 0.63], anchor="x2"),
            yaxis3=axis("Infusion (mL/min)", domain=[0.04, 0.30], anchor="x3"),
        )
        return render(self.stable_div_id(), traces, figure, 720, caption)
