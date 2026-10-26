#!/usr/bin/env bash
# Build the read-only workbench snapshot — a self-contained static SPA bundle
# (every investigation + study + assets) that anyone can browse with no server.
# Built by `vivarium-workbench-publish`; the same build is used locally (to
# preview) and by .github/workflows/publish-dashboard.yml (to publish to
# gh-pages:workbench/).
#
# GENERIC: base-path + interactive-url are passed in (the CI workflow derives
# them from the GitHub repo), so this script is workspace-agnostic — it ships
# with every workspace scaffolded from the template, no per-repo edits.
#
# Usage:
#   scripts/publish_dashboard.sh [OUT_DIR] [BASE_PATH] [INTERACTIVE_URL]
#     OUT_DIR          default: reports/published/workbench
#     BASE_PATH        e.g. /<repo>/workbench for GitHub Pages' project subpath
#                      (omit for a root-served bundle)
#     INTERACTIVE_URL  link back to the live/interactive repo (optional)
#
# Preview locally (no base-path → served at the root):
#   scripts/publish_dashboard.sh /tmp/dash
#   python -m http.server -d /tmp/dash 8080   # -> http://localhost:8080/
#
# Needs `vivarium-workbench-publish` on PATH (run via the workspace .venv, or
# `uv run`).
set -euo pipefail

WS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$WS_ROOT/reports/published/workbench}"
BASE_PATH="${2:-}"
INTERACTIVE_URL="${3:-}"

rm -rf "$OUT"

args=(--workspace "$WS_ROOT" --out "$OUT")
[ -n "$BASE_PATH" ] && args+=(--base-path "$BASE_PATH")
[ -n "$INTERACTIVE_URL" ] && args+=(--interactive-url "$INTERACTIVE_URL")

# Render every study figure BEFORE building the bundle. Rendered figures live in
# studies/<slug>/viz/ which is gitignored, so a fresh checkout (e.g. CI) has none
# and the published snapshot would ship with empty Visualizations tabs. Both
# renderers below read each study's committed runs.db — no server, no simulator
# engine — so they work in CI:
#   * render_viz                     -> each study's declared `visualizations:` (custom figures)
#   * comparative_runs.render_...    -> each study's `comparative_visualizations:` (baseline-vs-arm overlays)
# A figure that fails to render is skipped, never failing the publish.
PYTHONPATH="$WS_ROOT${PYTHONPATH:+:$PYTHONPATH}" python - "$WS_ROOT" <<'PY'
import sys
from pathlib import Path
ws = Path(sys.argv[1])
studies = ws / "workspace" / "studies"

# --- custom figures (declared `visualizations:`) ---
try:
    from vivarium_workbench.lib.investigation_viz_mutations import render_viz
    if studies.is_dir():
        for d in sorted(p for p in studies.iterdir() if (p / "study.yaml").is_file()):
            if not (d / "runs.db").is_file():
                continue
            try:
                body, status = render_viz(ws, {"name": d.name})
                n = len(body.get("viz_paths") or []) if isinstance(body, dict) else 0
                print(f"render: {d.name} -> {status} ({n} figure(s))")
            except Exception as e:  # noqa: BLE001 — never block the publish on one figure
                print(f"render: {d.name} -> error, skipped: {e}")
except Exception as e:  # noqa: BLE001 — older workbench without the lib entry
    print(f"render: custom figures skipped (render_viz unavailable: {e})")

# --- comparative figures (declared `comparative_visualizations:`) ---
# The live path renders these only at the END of an investigation run (which needs
# the engine); the renderer itself only reads runs.db, so it runs standalone here.
try:
    import yaml as _yaml
    from vivarium_workbench.lib.comparative_runs import (
        render_investigation_comparative_visualisations as _render_comp,
    )

    class _Job:  # the renderer only touches job.{items,update_item} on a per-figure error
        items = [None]
        def update_item(self, *a, **k):
            print(f"render(comparative): warning {k}")

    inv_dir = ws / "workspace" / "investigations"
    if inv_dir.is_dir():
        for inv in sorted(p for p in inv_dir.iterdir() if p.is_dir()):
            spec_path = inv / "investigation.yaml"
            if not spec_path.is_file():
                continue
            try:
                spec = _yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
                _render_comp(ws, inv.name, spec, _Job())
                import glob as _glob
                n = len(_glob.glob(str(studies / "*" / "viz" / "comparative_*.html")))
                print(f"render(comparative): {inv.name} -> {n} comparative figure(s) on disk")
            except Exception as e:  # noqa: BLE001
                print(f"render(comparative): {inv.name} -> error, skipped: {e}")
except Exception as e:  # noqa: BLE001 — older workbench without comparative_runs
    print(f"render(comparative): skipped ({e})")
PY

# The workspace's own package must be importable for build_core() registration.
PYTHONPATH="$WS_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  vivarium-workbench-publish "${args[@]}"

# Fix base-path on embed-figure urls. The publisher base-path-prefixes app assets
# and the custom figures, but a study's embed_visualizations are emitted with a
# RELATIVE url (`workspace/studies/.../viz/comparative_*.html`); under a project
# base-path they resolve against the study-detail page's own dir (…/studies/<slug>/)
# and 404. Rewrite those relative figure urls to the base-path-absolute location
# the files actually live at. (No-op for root hosting where BASE_PATH is empty.)
# Tracked upstream in upstream-issues/vivarium-workbench.md.
if [ -n "$BASE_PATH" ]; then
  find "$OUT/studies" -name 'index.html' -type f -print0 2>/dev/null | while IFS= read -r -d '' f; do
    perl -0pi -e "s{(\b(?:src|href)=\")workspace/}{\${1}${BASE_PATH}/workspace/}g" "$f"
  done
fi

# Strip bigraph-loom source maps (~half the bundle) — a read-only viewer never
# needs them — and disable Jekyll so files starting with _ are served.
find "$OUT" -name '*.map' -delete
touch "$OUT/.nojekyll"

echo "built read-only workbench bundle at $OUT ($(du -sh "$OUT" | cut -f1))"
