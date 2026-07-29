@echo off
setlocal
cd /d "%~dp0"

set "CONDA_ENV=fs-sweep-visualizer"

set "CONDA_BAT="
where conda.bat >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where conda.bat') do if not defined CONDA_BAT set "CONDA_BAT=%%I"
)

if not defined CONDA_BAT if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%USERPROFILE%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%USERPROFILE%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%LOCALAPPDATA%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%LOCALAPPDATA%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%LOCALAPPDATA%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%LOCALAPPDATA%\miniconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%ProgramData%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%ProgramData%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%ProgramData%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%ProgramData%\miniconda3\condabin\conda.bat"

if not defined CONDA_BAT (
    echo Conda was not found. Install Anaconda or Miniconda, then run the commands from SETUP_CONDA.md.
    pause
    exit /b 1
)

call "%CONDA_BAT%" activate "%CONDA_ENV%"
if errorlevel 1 (
    echo Could not activate conda env: %CONDA_ENV%
    echo If the environment is missing, run:
    echo conda env create -f environment.yml
    pause
    exit /b 1
)

python -m py_compile fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
if errorlevel 1 exit /b 1

python -m unittest discover -s tests
if errorlevel 1 exit /b 1

python -m pyflakes fs_sweep_app_spline.py preselection_shortlist.py tests/test_preselection_payload.py tests/test_app_contracts.py
if errorlevel 1 exit /b 1

set "NODE_EXE="
where node.exe >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where node.exe') do if not defined NODE_EXE set "NODE_EXE=%%I"
)
if not defined NODE_EXE if exist "%ProgramFiles%\nodejs\node.exe" set "NODE_EXE=%ProgramFiles%\nodejs\node.exe"
if not defined NODE_EXE if exist "%ProgramFiles(x86)%\nodejs\node.exe" set "NODE_EXE=%ProgramFiles(x86)%\nodejs\node.exe"
if not defined NODE_EXE if exist "%LOCALAPPDATA%\Programs\nodejs\node.exe" set "NODE_EXE=%LOCALAPPDATA%\Programs\nodejs\node.exe"

if defined NODE_EXE (
    "%NODE_EXE%" --check plotly_export_button/listener.js
    if errorlevel 1 exit /b 1
    "%NODE_EXE%" --check plotly_rx_toolbar/listener.js
    if errorlevel 1 exit /b 1
    "%NODE_EXE%" --check plotly_selection_bridge/listener.js
    if errorlevel 1 exit /b 1
    "%NODE_EXE%" --check plotly_selection_bridge/selection_table_module.js
    if errorlevel 1 exit /b 1
) else (
    echo Node.js not found. Skipping optional JavaScript syntax checks.
)

echo Checks passed.
exit /b 0
