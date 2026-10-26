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

# Render each study's declared figures BEFORE building the bundle. The rendered
# figures live in studies/<slug>/viz/ which is gitignored, so a fresh checkout
# (e.g. CI) has none and the published snapshot would ship with empty
# Visualizations tabs. render_viz is standalone — it reads each study's committed
# runs.db, no server and no simulator engine needed — so it works in CI. A study
# that fails to render is skipped, never failing the publish.
PYTHONPATH="$WS_ROOT${PYTHONPATH:+:$PYTHONPATH}" python - "$WS_ROOT" <<'PY'
import sys
from pathlib import Path
ws = Path(sys.argv[1])
try:
    from vivarium_workbench.lib.investigation_viz_mutations import render_viz
except Exception as e:  # noqa: BLE001 — older workbench without the lib entry
    print(f"render: skipped (render_viz unavailable: {e})")
    sys.exit(0)
studies = ws / "workspace" / "studies"
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
PY

# The workspace's own package must be importable for build_core() registration.
PYTHONPATH="$WS_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  vivarium-workbench-publish "${args[@]}"

# Strip bigraph-loom source maps (~half the bundle) — a read-only viewer never
# needs them — and disable Jekyll so files starting with _ are served.
find "$OUT" -name '*.map' -delete
touch "$OUT/.nojekyll"

echo "built read-only workbench bundle at $OUT ($(du -sh "$OUT" | cut -f1))"
