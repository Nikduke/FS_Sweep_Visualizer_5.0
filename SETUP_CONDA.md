# Conda Setup

This project should use its own conda environment, not `base`.

## Get the Project

```powershell
git clone git@github.com:Nikduke/FS_Sweep_Visualizer_5.0.git
cd FS_Sweep_Visualizer_5.0
```

## Recommended Environment

- Environment name: `fs-sweep-visualizer`
- Recommended Python: `3.12`
- Runtime packages: Streamlit, pandas, numpy, Plotly, openpyxl
- Development check package: pyflakes
- Install method: conda for Python and pip for project packages

Dependency versions are constrained in `requirements.txt`. Python minor version is not hard-pinned by the code, but Python `3.12` is recommended for package availability and portability.

## Create Environment

```powershell
conda env create -f environment.yml
```

## Activate Environment

```powershell
conda activate fs-sweep-visualizer
```

## Install or Refresh Dependencies Manually

Use this if the environment already exists or `environment.yml` was not used:

```powershell
python -m pip install -r requirements.txt
python -m pip install "pyflakes>=3,<4"
```

## Run App

```powershell
streamlit run fs_sweep_app_spline.py
```

Or:

```powershell
run_app.bat
```

## Test Environment

```powershell
python -m streamlit --version
python -m py_compile fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
python -m unittest discover -s tests
python -m pyflakes fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
```

Optional, if Node.js is installed:

```powershell
node --check plotly_export_button/listener.js
node --check plotly_rx_toolbar/listener.js
node --check plotly_selection_bridge/listener.js
node --check plotly_selection_bridge/selection_table_module.js
```

`run_checks.bat` performs these checks automatically when it finds Node.js.

## Troubleshooting

If `conda` is not found, open Anaconda Prompt or initialize conda for the shell.

If `streamlit` is not found after activation, run:

```powershell
python -m pip install -r requirements.txt
```

If `FS_sweep.xlsx` is absent, the app still runs but asks for an uploaded workbook.
