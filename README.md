# FS Sweep Visualizer

Streamlit app for frequency-sweep analysis of Excel workbooks with `R1`/`X1` and optionally `R0`/`X0` sheets.

This folder is a clean active project root. It contains only the current working app snapshot, required browser components, tests, sample workbook, and current setup documentation.

## Source Control

This is a Git repository. The `main` branch is published to:

```text
git@github.com:Nikduke/FS_Sweep_Visualizer_5.0.git
```

The tracked `FS_sweep.xlsx` file is the small smoke-test workbook. Other Excel workbooks and exported PNGs are ignored by default.

## What the App Does

- Loads a frequency-sweep workbook from uploaded `.xlsx` file or local `FS_sweep.xlsx`.
- Supports Positive and Zero sequence views.
- Preselection requires only the active sequence pair (`R1`/`X1` or `R0`/`X0`).
- Supports 50 Hz and 60 Hz base-frequency contexts.
- Shows `R vs X` scatter plus optional `X`, `R`, `X/R`, and `Z` line plots.
- Uses scatter and line-click selection with selected cases shown as diamonds.
- Provides case-part filters, color modes, selected-case table, CSV export, and selected-case hiding.
- Provides selection methods: Energinet thresholds, RX hull, Peak |Z|, Peak X, Risk, and Outliers, with capacitive variants where implemented.
- Provides full-legend PNG export buttons that avoid Plotly default legend cutting.

## Important Current Defaults

- Main app file: `fs_sweep_app_spline.py`
- Sample workbook: `FS_sweep.xlsx`
- Default display figure width: `1000`
- Default plot-area height: `400`
- Scatter height factor: `1.8` in normal mode and `1.5` in selection mode
- Custom fixed export width: `1000`
- Custom fixed export plot-area height: `400`
- Custom export scale: `4`
- Streamlit Cloud entry point, if deployed: `fs_sweep_app_spline.py`

## Folder Layout

```text
.
├── fs_sweep_app_spline.py
├── preselection_shortlist.py
├── requirements.txt
├── environment.yml
├── run_app.bat
├── run_checks.bat
├── FS_sweep.xlsx
├── plotly_export_button/
├── plotly_rx_toolbar/
├── plotly_selection_bridge/
├── tests/
├── README.md
├── SETUP_CONDA.md
├── PROJECT_CONTEXT.md
├── CLEANUP_SMOKE_CHECKLIST.md
├── STARTER_PROMPT.md
├── AGENTS.md
└── .gitignore
```

## Setup

Use a dedicated conda environment. Do not use `base`.

```powershell
conda env create -f environment.yml
conda activate fs-sweep-visualizer
```

If the environment already exists:

```powershell
conda activate fs-sweep-visualizer
python -m pip install -r requirements.txt
python -m pip install "pyflakes>=3,<4"
```

## Run

```powershell
conda activate fs-sweep-visualizer
streamlit run fs_sweep_app_spline.py
```

Or on Windows:

```powershell
run_app.bat
```

## Checks

```powershell
conda activate fs-sweep-visualizer
python -m py_compile fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
python -m unittest discover -s tests
python -m pyflakes fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
```

Optional JavaScript syntax checks if Node.js is installed:

```powershell
node --check plotly_export_button/listener.js
node --check plotly_rx_toolbar/listener.js
node --check plotly_selection_bridge/listener.js
node --check plotly_selection_bridge/selection_table_module.js
```

Or run:

```powershell
run_checks.bat
```

`run_checks.bat` activates the project conda environment, runs all Python contract tests, and runs JavaScript syntax checks automatically when Node.js is available. GitHub Actions runs the same checks for pushes and pull requests.

## Documentation to Read First

1. `PROJECT_CONTEXT.md`
2. `SETUP_CONDA.md`
3. `CLEANUP_SMOKE_CHECKLIST.md`
4. `STARTER_PROMPT.md`

## Machine-Specific Items

No secrets, API keys, database files, or `.env` files are required by the current app snapshot.

On a new laptop, install Anaconda or Miniconda and create the environment from `environment.yml`.

Node.js is only used for JavaScript syntax checks; no npm packages are required.
