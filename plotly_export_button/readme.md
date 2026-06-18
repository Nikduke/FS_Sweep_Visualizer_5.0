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
- JS reads `export_contract`.
- Contract covers plot index, scale, fixed export width/plot-height/scale, plot height, legend width, margins, font metrics, legend-row geometry, and fallback color.

Current status:
- export is positioned above the plot body, not in the sidebar `Show plots` section
- button label is `Export PNG`
- `Fixed size` is enabled by default and uses fixed width, fixed plot-area height, and fixed scale; disabling it exports at the current visible plot width/height behavior
- button text changes to `Exporting PNG...` while browser-side export runs
- `R vs X` PNG export omits the web-only frequency slider and uses the manual selected-case legend instead
- continues to export from the currently rendered plot state
- defensive export helpers use debug-only warnings instead of silent catches
