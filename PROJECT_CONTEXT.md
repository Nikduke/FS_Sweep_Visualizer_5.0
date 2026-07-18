# Project Context

## Project

FS Sweep Visualizer is a Streamlit app for reviewing frequency-sweep impedance data from Excel workbooks.

This folder is the active working project root. It is not a transfer wrapper and not a historical archive.

## Purpose

The app helps inspect many frequency-sweep cases, select important cases, and export plots with readable legends.

Primary workflow:

1. Load `FS_sweep.xlsx` from this folder or upload another `.xlsx` workbook.
2. Choose sequence, base frequency, and location.
3. Use `R vs X` scatter for selection.
4. Review `X`, `R`, `X/R`, and `Z` line plots.
5. Use case filters and selection methods to shortlist cases.
6. Export PNGs with full legends.
7. Export selected cases as CSV when needed.

## Current State

Current snapshot includes the latest local app updates:

- Default figure width is `1000`.
- Plot-area height default is `400`.
- `R vs X` scatter keeps height factor `1.5` relative to plot-area height.
- Scatter now respects manual/default figure width when Auto width is off.
- Custom `Export PNG` has `Fixed size` checked by default.
- Fixed export uses width `1000`, plot-area height `400`, and scale `4`.
- Scatter fixed export uses the scatter 1.5-height value.
- Line plot export preserves selected/current legend state and avoids Plotly default legend cutting.
- Scatter export removes the web-only frequency slider and builds a selected-case legend.

## Folder Organization

```text
fs_sweep_app_spline.py                  Main Streamlit app
preselection_shortlist.py               Selection/ranking algorithms and compact payload helpers
requirements.txt                        Runtime pip dependencies
environment.yml                         Conda environment definition
run_app.bat                             Windows launcher using dedicated conda env
run_checks.bat                          Windows check runner using dedicated conda env
FS_sweep.xlsx                           Small sample workbook for local smoke testing
plotly_export_button/                   Custom PNG export component
plotly_rx_toolbar/                      Custom scatter frequency/preselection/selection toolbar
plotly_selection_bridge/                Custom case-selection/filter bridge
tests/test_preselection_payload.py      Unit tests for selection payload/ranking helpers
README.md                               Project overview and quick start
SETUP_CONDA.md                          Detailed conda setup
CLEANUP_SMOKE_CHECKLIST.md              Manual regression checklist
STARTER_PROMPT.md                       Prompt for Codex on new laptop
AGENTS.md                               Local Codex working rules
```

## Important Files

- `fs_sweep_app_spline.py`: app UI, workbook loading, plotting, session state, custom component calls.
- `preselection_shortlist.py`: Energinet, RX hull, Peak |Z|, Peak X, Risk, Outliers, compact preselection payloads.
- `plotly_selection_bridge/listener.js`: case filters, selection table, selected-case propagation.
- `plotly_rx_toolbar/listener.js`: scatter frequency controls and selection method UI.
- `plotly_export_button/listener.js`: full-legend PNG export logic.

## Required Conda Environment

Recommended environment name: `fs-sweep-visualizer`.

Create:

```powershell
conda env create -f environment.yml
```

Activate:

```powershell
conda activate fs-sweep-visualizer
```

Run:

```powershell
streamlit run fs_sweep_app_spline.py
```

## Tests and Checks

Core checks:

```powershell
python -m py_compile fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py
python -m unittest tests.test_preselection_payload
python -m pyflakes fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py
```

Optional JavaScript checks if Node.js exists:

```powershell
node --check plotly_export_button/listener.js
node --check plotly_rx_toolbar/listener.js
node --check plotly_selection_bridge/listener.js
node --check plotly_selection_bridge/selection_table_module.js
```

## Current App Logic Notes

- Workbook data is loaded from Excel and converted into compact in-memory arrays.
- Base frequency can be 50 Hz or 60 Hz.
- Sequence can be Positive or Zero.
- Preselection validates only the active R/X sheet pair, so Positive-only or Zero-only workbooks remain supported.
- App uses Streamlit session state for selections, filters, cached figures, and custom component state.
- Custom browser components communicate through Streamlit component iframes and parent-window Plotly state.
- Preselection builds the compact browser payload directly, avoiding a duplicate raw payload in memory.
- Selection methods are separate and can be combined. Method outputs are additive unless manual selection changes state.
- Peak |Z| and Peak X support exact harmonic and harmonic-band modes.
- Capacitive variants are computed inside each relevant method, not post-filtered after normal ranking.

## Configuration Requirements

No `.env` file is required.

No API keys, credentials, local database, or external service tokens are required.

The only machine-specific requirement is a local Anaconda or Miniconda installation.

## Known Issues and Risks

- Very large Excel files can still stress Streamlit Cloud memory and browser rendering.
- JavaScript components depend on Plotly DOM structure in the Streamlit page.
- Fixed PNG export depends on browser-side Plotly image generation; very large legends can produce large PNGs.
- Selection-method correctness should be checked with engineering judgment, especially for new datasets.
- Node.js is optional; without it, JavaScript syntax checks cannot run locally.

## Pending Work

- Further performance profiling on large uploaded workbooks.
- More manual regression testing after UI/export changes.
- Possible future cache budget/LRU control for Streamlit Cloud safety.
- Possible additional tests for browser component state are not currently automated.

## What Codex Should Read First

1. `README.md`
2. `SETUP_CONDA.md`
3. `PROJECT_CONTEXT.md`
4. `CLEANUP_SMOKE_CHECKLIST.md`
5. Actual code files relevant to the requested change

## What Codex Should Verify Before Editing

- Confirm current folder is the active project root.
- Inspect actual code before trusting documentation.
- Check whether a change affects Streamlit Python, custom JS components, or both.
- Check whether docs need updates after meaningful code changes.
- Run the smallest relevant checks after edits.
