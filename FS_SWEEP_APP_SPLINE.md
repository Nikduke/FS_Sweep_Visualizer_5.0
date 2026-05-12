# FS Sweep Visualizer - Current Implementation

This document reflects:
- `fs_sweep_app_spline.py`
- `preselection_shortlist.py`
- `plotly_selection_bridge/listener.js`
- `plotly_selection_bridge/selection_table_module.js`
- `plotly_export_button/listener.js`
- `plotly_rx_toolbar/listener.js`

## Scope

The app renders:
- `X`, `R`, `X/R` line plots
- optional `R vs X` scatter

Core design:
- Streamlit reruns for context changes (data/sequence/location/layout/base frequency).
- JS direct restyling for high-frequency interactions (case filters/selection/color/harmonics/method toggles).
- JS-heavy UI helpers are externalized into dedicated component assets (no large inline JS blocks in Python).
- deterministic preselection metrics are computed server-side once per context and consumed client-side without rerun.
- default layout renders `R vs X` scatter before line plots in the main area.
- optional `Selection mode` changes layout only: row 1 is `R vs X` + `X`, row 2 is `R` + `X/R` for enabled plots.
- data-scoped Streamlit cache keys are pruned on file/context changes to avoid stale-session growth.
- JS widget state/API stores are pruned to the active `{data_id}|{chart_id}` context.
- JS cross-component state names are explicit component contracts:
  - `window.parent.__fsCaseUiStore` stores selection/filter state.
  - `window.parent.__fsCaseUiApi` exposes toolbar-facing selection actions.
  - `fsCaseUiStateChanged` notifies sibling components after no-rerun state changes.
- selected-location preselection payload is cached in session state by:
  - `preselection_payload:{data_id}:{seq_label}:{location}` (single active base payload, overwritten on base switch).
  - payload sent to JS uses compact array/index format (`compact_v3`) to reduce rerun transfer size.
- on chart-context switches (`base frequency`, `location`, `Positive/Zero` sequence), heavy sequence caches are evicted before rebuild to reduce peak-memory spikes on constrained hosts.
- non-active sequence/location/chart cache entries are pruned proactively in the same data session.
- uploaded workbooks are parsed once and cached as live `SweepSheet` objects in session state:
  - `uploaded_data:{data_id}:workbook`
  - reruns reuse the parsed workbook directly; legacy NPZ cache entries are migrated once then removed.
- raw XLSX bytes are used only for hashing/load step and are not kept as active runtime data by app code.
- sheet value columns are converted to `float32` during load to reduce in-memory footprint on large datasets.
- XLSX sheet conversion uses block conversion for all case columns instead of per-case conversion loops.
- line plots use frequency Hz as internal Plotly `x` data and harmonic-number tick labels, which removes repeated per-trace frequency `customdata` while preserving exact frequency hover.
- cached line/scatter figure signatures use compact case/color hashes instead of serializing full case/color maps on every rerun.
- figure cache entries are LRU-tracked with env-controlled cap `FS_SWEEP_MAX_FIGURE_CACHE_ITEMS` (default `8`, `0` disables).
- preselection expects the internal `SweepSheet` representation; DataFrame fallback logic is not part of the active app path.

## Dependency Policy

- `requirements.txt` pins tested major-version ranges instead of open-ended minimums.
- Streamlit is capped below `1.56` while the app still uses `use_container_width`, which is supported in the current local/Cloud baseline but warned as deprecated by newer Streamlit releases.
- Pandas/Numpy/Plotly/OpenPyXL are capped to their current major versions to avoid unplanned Cloud upgrades changing runtime behavior.

## Export Contract

- Line-plot PNG export uses `plotly_export_button`.
- The custom export button is shown above each enabled line plot as `Export PNG`.
- This custom export exists because Plotly's default modebar export can cut long legends.
- Python passes export sizing/layout values as one `export_contract` object.
- The export component uses the currently rendered Plotly DOM state, so selected-only visibility/legend styling is reflected in exported PNGs.
- Export component keys are stable by plot filename/label to reduce remount flicker while plot index and layout are passed through the current contract args.

## Static Checks

- GitHub Actions workflow `.github/workflows/static-checks.yml` runs:
  - Python syntax check for `fs_sweep_app_spline.py` and `preselection_shortlist.py`
  - `pyflakes` for the same Python files
  - `node --check` for the three JS component listeners plus `selection_table_module.js`
- `CLEANUP_SMOKE_CHECKLIST.md` remains the manual browser regression checklist for interactions that static checks cannot cover.

## Sidebar Layout (current)

1. `Data Source`
2. `Analysis context`
   - `Sequence`
   - `Base frequency`
     - defaults once per new workbook from max loaded frequency (`<=330 Hz` => `50 Hz`, `<=390 Hz` => `60 Hz`)
     - user changes are preserved until another workbook is loaded
   - `Location`
   - helper text: changing these rebuilds plots
3. `Case Filters & Selection`
   - JS widget panel, including case-part filters, color, selection list, selected-case table, and harmonics
   - the panel owns its own dynamic frame height so following controls do not cover it
4. `Show plots`
   - `R vs X scatter` remains the first checkbox row
   - `X`, `R`, and `X/R` checkboxes share one compact row
   - line-plot export buttons are no longer embedded in this sidebar section
   - `Selection mode` checkbox is last and changes layout only:
     - `R vs X` and `X` share the first row evenly when both are enabled
     - `R` and `X/R` share the second row evenly when both are enabled
     - a single enabled plot in a row uses full width
     - charts stretch to the available column width while this mode is enabled
     - line-plot legends are hidden in this compact selection layout so the plot heights stay visually aligned
     - line-plot axis titles use the softer default-like style used by the scatter
   - no sidebar legend-width controls (width is internal)
5. `Display settings` (collapsed by default)
   - plot height
   - width mode/figure width
   - spline toggle/smoothing

## JS Widget (no rerun)

Rendered by `plotly_selection_bridge`:
- case-part filters (excluding location)
  - color dots are shown to the right of case-part values for the active color grouping
  - works for explicit `Case part N` color mode and for `Auto` (uses auto-selected hue part)
- color mode (`Auto`/by case part)
- selection controls:
  - `Clear list` / `Download selected CSV` are shown above the selected-cases table in the widget panel
  - `Hide unselected` stays in the scatter control row when scatter is shown
  - when scatter is hidden: `Hide unselected` is shown in the widget panel
  - add list (paste/import; accepts space/comma/tab/newline separation)
  - remove selected rows (`Del`)
  - selected CSV download
- harmonics controls:
  - show harmonic lines
  - bin width (Hz)
  - harmonic/bin guide lines are generated from full baseline harmonic range (not from current zoom window)
- method controls (in the scatter toolbar default-open `Selection methods` section):
  - `Energinet` toggle + editable `T2/T3/T4` + `Top N`
  - `RX hull` toggle + `Top N` + `Capacitive (N)`
  - `Peak |Z|` toggle + `Top N/h` + `Capacitive (N)`
  - `Risk` toggle + `Top N` + `Capacitive (N)`
  - `Outliers` toggle + `Top N` + `Capacitive (N)`
  - capacitive modes are computed inside each method from negative-X points (`X < 0`), not by post-filtering normal results
  - method toggles append/remove method-sourced candidates from selection state without rerun
  - `Top N` is method-specific (`0` => all candidates for that method)

## Selection Method Formulas

- `Energinet`: ranks cases where harmonic-band peak `|Z|` exceeds editable thresholds at 2nd/3rd/4th harmonic. Score is the maximum threshold ratio.
- `RX hull`: for each harmonic from 2 to available range capped at 6, finds each case's harmonic-band peak `|Z|` point in R/X space and selects convex-hull vertices. Ranking uses earliest selected harmonic, then vertex count.
- `Peak |Z|`: ranks cases separately within each harmonic band over harmonics 2..6. `Top N/h` selects the top N cases per harmonic and uses the union of those cases.
- `Risk`: ranks cases by weighted score from normalized peak `|Z|`, robust local prominence over cohort median/MAD, area above cohort median, damping proxy `log1p(|Z| / max(|R|, 1))`, and proximity to harmonic center.
- `Outliers`: selects robust outliers by harmonic-band peak `|Z|` using MAD z-score threshold `3.5`; if MAD collapses, uses 95th percentile fallback.
- For `RX hull`, `Peak |Z|`, `Risk`, and `Outliers`, `Capacitive` mode recomputes the method using only candidate points with `X < 0`; for `Peak |Z|`, this is still Top N per harmonic.

## Visibility And Legend Rules

Layer 1 (case-part filters):
- filtered-out cases are hidden in lines and scatter
- filtered-out cases are hidden from legends

Layer 2 (selection):
- default: non-selected visible cases are dimmed
- `Hide unselected`: non-selected visible cases are hidden in line plots
- when selection is non-empty: line legends show selected cases only
- scatter keeps allowed points visible for continued picking

Selection is sticky across case-part changes:
- selected cases hidden by filters remain in selection state
- they reappear when filters include them again

Line legend appearance:
- line traces are rendered in line-only mode, so legend swatches are line-only (no dot marker symbol).

Line x-axis implementation:
- visual axis remains `Harmonic number n = f / f_base`.
- internal Plotly x-values are frequency Hz, with tick labels mapped to harmonic numbers.
- hover shows exact `f` from `%{x}` without repeated per-trace frequency `customdata`.

## Scatter Behavior (`R vs X`)

- one scatter trace is rendered; scatter frequency state is controlled client-side.
- in-plot frequency slider remains visible.
  - slider steps are control signals (`method='skip'`), not Plotly animation frames.
  - JS reads `layout.meta.rx_single_trace` and restyles trace `x/y` for selected frequency.
  - scatter payload uses compact `version=2` flat step-major arrays (`x_flat`/`y_flat` + `point_count`) instead of nested per-step arrays.
  - server build uses vectorized nearest-frequency indexing and vectorized flat payload creation.
- `Prev frequency` / `Next frequency` buttons:
  - call shared selection API (`stepRxFrequency`) for no-rerun stepping.
- direct frequency entry:
  - scatter toolbar `Frequency` group includes `Prev`, `Next`, `Set f (Hz)` field, and `Set` button.
  - entered value snaps to the nearest available frequency step without rerun.
- selection controls:
  - scatter toolbar `Selection` group mirrors selected/visible/hidden counts from the sidebar panel.
  - `Clear` and `Download CSV` are duplicated in this toolbar and call the same shared JS selection API as the sidebar panel.
- scatter status line:
  - `R vs X points shown: <count> | Frequency steps: <steps>`
  - `<count>` is case-filtered visible point count.
- modebar `Reset axes` returns to location-based baseline bounds.
- click selection toggles by case id and feeds shared JS state.
- line plots (`X`, `R`, `X/R`) also support click selection by case id and feed the same shared JS selection state.
- selected point styling:
  - selected visible points use symbol `diamond`
  - non-selected points keep `circle`
  - dimming behavior is unchanged.
- hover:
  - shows case name, `R`, and `X`.
  - frequency is shown by slider current value and title.

## Zoom Behavior

- no custom zoom persistence bridge is used.
- zoom/pan/reset behavior is native Plotly behavior.
- figure `uirevision` persistence is not forced by app code.
- line-plot x scaling follows Streamlit base-frequency control (`f_base`) on rerun.
- harmonic guide lines are converted client-side to the active line x-axis unit.
- Energinet threshold defaults are base-frequency specific:
  - `50 Hz`: `400/600/2400`
  - `60 Hz`: `450/800/3000`

## Export Behavior

- on-page line-plot legends are rendered below plots (horizontal) with fixed reserved legend area.
- legend column width is auto-calculated internally (not user-configured in sidebar).
- modebar export remains available.
- line full-legend export (`Export PNG` above each line plot) reads current line visibility/style state.
- hidden cases are excluded from export legend.

## Loading/Status States

- workbook parse paths use `Loading workbook...`.
- large uploaded workbooks show `Large file detected: first load can take longer`.
- preselection/plot rebuild paths show `Building plots for <location> / <base Hz>...`.
- custom PNG export button shows `Exporting PNG...` while browser-side export is running.
