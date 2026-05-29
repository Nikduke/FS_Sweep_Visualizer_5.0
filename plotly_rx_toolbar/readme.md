# plotly_rx_toolbar

Mini Streamlit component used by `fs_sweep_app_spline.py` to render the grouped toolbar under `R vs X` scatter.

Responsibilities:
- `Frequency` group:
  - `Prev frequency` / `Next frequency` stepping
  - shared bridge API `stepRxFrequency(delta)` (single-trace scatter restyle, no rerun)
  - `Set f (Hz)` field + `Set` button
  - uses shared bridge API to snap to the nearest available scatter frequency without rerun
- default-open `Selection methods` section:
  - `Energinet` toggle with editable `T2/T3/T4` thresholds and `Top N`
  - `RX hull` toggle with `Top N/h` and `Capacitive (N)`; it selects strongest hull cases per harmonic, then uses their union
  - `Peak |Z|` toggle with `Top N/h` and `Capacitive (N)`; it selects top cases per harmonic, then uses their union
  - `Risk` toggle with `Top N` and `Capacitive (N)`
  - `Outliers` toggle with `Top N` and `Capacitive (N)`
  - each row has a compact `?` hover note explaining the method
  - capacitive counts are current visible candidate counts from method-specific negative-X computation (`X < 0`)
- `Selection` group:
  - `Hide unselected` checkbox synchronized with shared JS selection API
  - selected/visible/hidden summary mirrored from the sidebar selected-cases panel
  - `Clear` and `Download CSV` actions duplicated from the sidebar panel and routed through the same shared selection API
- shared-state polling is fallback-only and runs at a low frequency; normal sync uses `fsCaseUiStateChanged` events
- method controls operate via selection API and update selection without Streamlit rerun

`Clear list` / `Download selected CSV` remain in the selection panel above the selected-cases table; toolbar copies exist for faster scatter-selection workflows.

Layout/styling:
- group labels are inline bold text, not separate headers, to keep height compact
- action controls use the same simple bordered button language as the selection panel
- compact controls use focus-visible and disabled states

The component consumes selection state/actions through `window.parent.__fsCaseUiApi`.

Shared JS contract:
- action API store: `window.parent.__fsCaseUiApi`
- state-change event: `fsCaseUiStateChanged`
- both names are constants in the toolbar and selection bridge.

Error handling:
- defensive browser/iframe failures use debug-only warnings instead of silent catches.
- warnings are silent unless `debug_log` is passed in component args.
