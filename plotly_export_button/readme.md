# plotly_export_button

Mini Streamlit component used by `fs_sweep_app_spline.py` to render the `Export PNG` button above enabled plots (`R vs X`, `X`, `R`, `X/R`).

Responsibilities:
- render compact bordered button UI with focus-visible and disabled/loading states
- collect active Plotly trace visibility/style from the target plot
- generate full-legend PNG in browser with manual legend layout
- for `R vs X`, build the manual legend from selected visible cases via the shared selection API, with rendered marker-symbol fallback

No Streamlit rerun is triggered by button clicks.

Why it exists:
- Plotly's default modebar PNG export can cut long horizontal legends.
- This component rebuilds a temporary offscreen export figure with a manual full legend so selected-only legends are preserved.

Input contract:
- Python passes one nested `export_contract` object for layout/export sizing.
- JS reads `export_contract` first and keeps legacy top-level arg fallback for compatibility.
- Contract covers plot index, scale, plot height, legend width, margins, font metrics, legend-row geometry, and fallback color.

Current status:
- export is positioned above the plot body, not in the sidebar `Show plots` section
- button label is `Export PNG`
- button text changes to `Exporting PNG...` while browser-side export runs
- continues to export from the currently rendered plot state
- defensive export helpers use debug-only warnings instead of silent catches
