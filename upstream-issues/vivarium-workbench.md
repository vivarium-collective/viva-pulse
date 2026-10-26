# vivarium-workbench issues found from viva-pulse

## Published snapshot: `embed_visualizations` figure urls are not base-path-prefixed → 404

**Where:** `vivarium_workbench/lib/report.py::_apply_live_base_path` (and the
study-detail page generator that emits `embed_visualizations` entries).

**Symptom:** In a read-only snapshot published under a project base-path (e.g.
GitHub Pages at `/<repo>/workbench`), a study's Visualizations tab shows a
GitHub-Pages **404** for every `embed_visualizations` figure (the
`comparative_*.html` overlays), while the custom `visualizations:` figures render
fine.

**Cause:** The custom figures are emitted with a base-path-absolute url
(`/<repo>/workbench/workspace/studies/<slug>/viz/<fig>.html`), but
`embed_visualizations[].url` is emitted **relative**
(`workspace/studies/<slug>/viz/<fig>.html`). The study-detail page is loaded in
an iframe whose document URL is `…/studies/<slug>/`, so the relative url resolves
to `…/studies/<slug>/workspace/studies/<slug>/viz/<fig>.html` → 404. The
base-path rewriter `_apply_live_base_path` only matches `src|href="assets/…"` and
`src|href="/(assets|bigraph-loom|reports)/…"`, so a `workspace/…` relative url is
never prefixed.

**Suggested fix:** Have the study-detail generator emit `embed_visualizations`
urls base-path-absolute like the custom figures, or extend `_apply_live_base_path`
to also rewrite relative `src|href="workspace/…"` urls.

**Workaround in viva-pulse:** `scripts/publish_dashboard.sh` post-processes the
published `studies/*/index.html` to rewrite relative `workspace/…` figure urls to
`<base-path>/workspace/…`. (It also renders the comparatives from the committed
`runs.db` before publishing, since the live path renders them only at the end of
an engine-backed investigation run.)
