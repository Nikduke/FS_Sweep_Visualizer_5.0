# plotly_selection_bridge

Client-side control bridge for case filtering, selection, color styling, harmonics overlays, and scatter status/frequency updates.

## Files

- `index.html`
- `selection_table_module.js` (selection table helpers + selection API bridge)
- `listener.js` (plot restyling, panel helpers, scheduler, event wiring)

`listener.js` structure:
- pure panel HTML helpers (`panelCss`, `renderPanelHtml`, row/filter render helpers)
- panel event binding (`bindPanelEvents`)
- plot restyle/apply helpers
- Streamlit render message coordinator (`renderPanel`)

Related sibling components (same repo):
- `../plotly_export_button/*` (line-plot full-legend export button UI/logic)
- `../plotly_rx_toolbar/*` (scatter prev/next + selection/method toolbar row)

## Input Args

- `data_id` (string)
- `chart_id` (string)
- `plot_ids` (string[]): expected visible plot kinds (`rx`, `x`, `r`, `xr`); JS classifies actual DOM plots by trace metadata
- `cases_meta` (object[]):
  - `case_id` (string)
  - `display_case` (string)
  - `parts` (string[])
- `part_labels` (string[])
- `color_by_options` (string[])
- `color_maps` (object): `{option -> color_hex[]}` aligned to `cases_meta` order; legacy `{case_id -> color_hex}` maps are still read defensively.
- `auto_color_part_label` (string): case-part label used when `Color=Auto` (for filter color dots)
- `color_by_default` (string)
- `show_only_default` (bool)
- `selected_marker_size` (float)
- `dim_marker_opacity` (float)
- `selected_line_width` (float)
- `dim_line_width` (float)
- `dim_line_opacity` (float)
- `dim_line_color` (string)
- `f_base` (float)
- `n_min` (float)
- `n_max` (float)
- `show_harmonics_default` (bool)
- `bin_width_hz_default` (float)
- `rx_status_dom_id` (string): optional parent DOM id for scatter status text
- `rx_freq_steps` (int): fallback step count for status text
- `preselection_payload` (object): server-precomputed selection-method candidate data
  - compact format (`format=compact_v3`) is the active payload contract:
    - `case_ids` + array metrics (`energinet.z2/z3/z4/...`)
    - `RX hull` (`iec_modes`) `all` and `capacitive` modes encoded with `case_idx`, `vertex_orders`, and `vertex_zmax`
    - `Peak |Z|`, `Risk`, and `Outliers` modes encoded with `case_idx`, `scores`, `zmax`, and `harmonic`
    - `RX hull` and `Peak |Z|` use per-harmonic `Top N/h`, then union selected cases
- `energinet_t2_default` (float)
- `energinet_t3_default` (float)
- `energinet_t4_default` (float)
- `reset_token` (int)
- `selection_reset_token` (int)
- `render_nonce` (int)
- `enable_selection` (bool)
- `spline_enabled` (bool): hints JS re-apply schedule (longer tail when spline is enabled)

## Behavior

1. Renders control panel UI inside component iframe.
2. Computes allowed cases from case-part filters.
3. Applies selection style layer:
   - dim mode (default)
   - hide mode (`Hide unselected`)
4. Restyles line plots (`x/r/xr`) without rerun:
   - applies `visible`, `showlegend`, line color/width/opacity
   - when selection exists, legend entries are limited to selected cases
   - line plots use frequency Hz as internal x-values and harmonic-number tick labels; base-frequency scaling is server-managed in Streamlit reruns
5. Applies harmonics overlays on line plots from JS controls.
6. Restyles scatter points (`rx`) without rerun.
   - scatter keeps allowed points visible for picking; `Hide unselected` is line-plot-only.
   - selected points use `diamond` symbol; others use `circle`.
7. Updates scatter status text in parent DOM (`rx_status_dom_id`) with case-filtered visible count.
8. Handles click selection toggle on scatter and line plots (`X`, `R`, `X/R`) into the same shared selection state.
   - click case-id resolution validates candidates against known case IDs and falls back through trace metadata.
9. Supports selection-table actions (clear/remove/import/csv).
   - `Clear list` / `Download selected CSV` are rendered above the selected-cases table.
   - when scatter is hidden, `Hide unselected` is also rendered in the panel.
   - import list tokenization accepts space/comma/tab/newline separation.
10. Handles scatter frequency changes without rerun:
    - primary path: single-trace restyle from `layout.meta.rx_single_trace` on `plotly_sliderchange`
    - active scatter payload contract is `version=2`: flat step-major `x_flat`/`y_flat` arrays plus `point_count`
11. In case-part filters, shows color dots to the right of values for active `Color` grouping.
    - if `Color=Auto`, uses `auto_color_part_label`.
12. Exposes selection control API at `window.parent.__fsCaseUiApi[{data_id}|{chart_id}]` for scatter-row controls.
    - includes state/query methods plus selection/method mutators
    - includes scatter stepping helper `stepRxFrequency(delta)` for toolbar prev/next controls
    - includes exact frequency setter `setRxFrequencyHz(rawHz)` and current-frequency state fields for toolbar sync
    - includes selected/visible/hidden counts for toolbar summary sync
    - includes `clearSelection()` and `downloadSelectedCsv()` so the scatter toolbar can duplicate panel actions without adding a Streamlit rerun
13. Apply scheduler uses bounded multi-pass probes and stops early once expected plots are bound/stable.
    - plot DOM lookup and plot-kind classification are cached by render nonce.
14. Maintains source-aware selection model:
    - manual selections (scatter clicks/import/remove)
    - Energinet method selections
    - RX hull method selections
    - Peak |Z| / Risk / Outliers method selections
    - method toggles, method-specific `Top N`, method-specific capacitive mode, and Energinet thresholds are applied client-side without rerun.

## State Model

- stored in `window.parent.__fsCaseUiStore`
- key: `{data_id}|{chart_id}`
- persists across normal reruns in same page session
- resets on `reset_token` change
- stale entries are pruned to the active `{data_id}|{chart_id}` key
- selection includes `manualSelectedCases` and method-derived sets merged into `selectedCases`

## Cross-Component Contract

- state store: `window.parent.__fsCaseUiStore`
- action API store: `window.parent.__fsCaseUiApi`
- state-change event: `fsCaseUiStateChanged`
- these names are constants in the JS components to avoid hidden string drift.

## Error Handling

- component exceptions that can be safely ignored are routed through debug-only warning helpers.
- debug warnings are silent by default and only log when `debug_log` is supplied in component args.

## Python Roundtrip Policy

- normal interactions do not emit `streamlit:setComponentValue`
- updates are applied directly to existing Plotly DOM
