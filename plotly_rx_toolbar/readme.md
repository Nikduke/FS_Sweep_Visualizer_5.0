# plotly_rx_toolbar

Mini Streamlit component used by `fs_sweep_app_spline.py` to render the grouped toolbar under `R vs X` scatter.

Responsibilities:
- `Frequency` group:
  - `Prev frequency` / `Next frequency` stepping
  - shared bridge API `stepRxFrequency(delta)` (single-trace scatter restyle, no rerun)
  - `Set f (Hz)` field + `Set` button
  - uses shared bridge API to snap to the nearest available scatter frequency without rerun
- `Selection` group:
  - `Hide unselected` checkbox synchronized with shared JS selection API
  - selected/visible/hidden summary mirrored from the sidebar selected-cases panel
  - `Clear` and `Download CSV` actions duplicated from the sidebar panel and routed through the same shared selection API
- shared-state polling is fallback-only and runs at a low frequency; normal sync uses `fsCaseUiStateChanged` events
- `Preselect` group:
  - `Energinet` toggle with editable `T2/T3/T4` thresholds and `Top N`
  - `IEC` toggle with `Top N`
  - `Capacitive (N)` IEC filter; `N` is the current visible capacitive IEC candidate count, and when enabled IEC uses only negative-X harmonic points (`X < 0`)
  - both operate via selection API and update selection without Streamlit rerun

`Clear list` / `Download selected CSV` remain in the selection panel above the selected-cases table; toolbar copies exist for faster scatter-selection workflows.

Layout/styling:
- group labels are inline bold text, not separate headers, to keep height compact
- action controls use the same simple bordered button language as the selection panel
- minimum action height is 32px with focus-visible and disabled states

The component consumes selection state/actions through `window.parent.__fsCaseUiApi`.

Shared JS contract:
- action API store: `window.parent.__fsCaseUiApi`
- state-change event: `fsCaseUiStateChanged`
- both names are constants in the toolbar and selection bridge.

Error handling:
- defensive browser/iframe failures use debug-only warnings instead of silent catches.
- warnings are silent unless `debug_log` is passed in component args.
