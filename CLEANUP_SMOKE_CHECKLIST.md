# Cleanup Smoke Checklist

Run after meaningful app changes. Use current conda environment `fs-sweep-visualizer`.

Prefer `run_checks.bat` on Windows. It activates the correct environment and runs Node.js syntax checks automatically when Node.js is available.

## Static Checks

```powershell
python -m py_compile fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
python -m unittest discover -s tests
python -m pyflakes fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
```

Optional if Node.js is installed:

```powershell
node --check plotly_export_button/listener.js
node --check plotly_rx_toolbar/listener.js
node --check plotly_selection_bridge/listener.js
node --check plotly_selection_bridge/selection_table_module.js
```

## App Startup

- Start app with `run_app.bat` or `streamlit run fs_sweep_app_spline.py`.
- Confirm local `FS_sweep.xlsx` loads.
- Confirm uploading another `.xlsx` workbook works.

## Source Control

- Confirm `git status -sb` contains only the intended changes before committing.
- Do not add `__pycache__`, private workbooks, or exported PNGs.

## Context Switching

- Switch Positive / Zero sequence.
- Switch base frequency 50 Hz / 60 Hz.
- Switch location.
- Toggle spline on/off.

## Display and Plot Layout

- Change plot-area height.
- Toggle Auto width.
- If Auto width is off, change Figure width.
- Confirm `R vs X` scatter respects Display Settings width and keeps 1.5 height factor.
- Toggle `R vs X scatter`, `X`, `R`, `X/R`, and `Z` plots.
- Toggle Selection mode.
- Confirm normal layout stacks scatter and line plots.
- Confirm Selection mode places scatter and `X` in first row and enabled `R`, `X/R`, `Z` in second row.

## Selection and Filters

- Use case-part filters.
- Change color mode.
- Click scatter point; selected point becomes diamond.
- Click line trace; same case selection updates.
- Toggle `Hide unselected`.
- Import case list with spaces, commas, tabs, and newlines.
- Remove selected row with Delete.
- Clear selected list.
- Download selected CSV.

## Selection Methods

- Open Selection methods.
- Toggle Energinet and edit thresholds.
- Toggle RX hull.
- Toggle Peak |Z| exact and band modes.
- Toggle Peak X exact and band modes.
- Toggle Risk.
- Toggle Outliers.
- Test capacitive variants for relevant methods.
- Change Top N values.
- Confirm selected cases update in scatter and line plots.
- Confirm the toolbar refreshes after each method toggle and Clear selected list.

## Scatter Frequency Controls

- Move in-plot slider.
- Confirm harmonic-order labels appear along the in-plot slider and the readout remains in Hz.
- Use Previous frequency / Next frequency.
- Use Set f (Hz).
- Confirm frequency value and scatter points update together.

## Export

- Export scatter PNG with `Fixed size` on and off.
- Export `X`, `R`, `X/R`, and `Z` PNGs when enabled.
- Confirm long legends are not cut.
- Confirm selected-only legend state is reflected in export.
- Confirm scatter export omits the frequency slider.
