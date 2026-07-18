@echo off
setlocal
cd /d "%~dp0"

set "CONDA_ENV=fs-sweep-visualizer"
set "APP_FILE=fs_sweep_app_spline.py"

if not exist "%APP_FILE%" (
    echo Cannot find %APP_FILE% in this folder.
    pause
    exit /b 1
)

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
    echo Conda was not found. Install Anaconda or Miniconda, then run:
    echo conda env create -f environment.yml
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

echo Starting FS Sweep Visualizer with conda env: %CONDA_ENV%
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
set "STREAMLIT_SERVER_SHOW_EMAIL_PROMPT=false"
python -m streamlit run "%APP_FILE%" --server.showEmailPrompt false --browser.gatherUsageStats false
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo App exited with code %EXIT_CODE%.
    echo If the environment is missing, run:
    echo conda env create -f environment.yml
    pause
)

exit /b %EXIT_CODE%
