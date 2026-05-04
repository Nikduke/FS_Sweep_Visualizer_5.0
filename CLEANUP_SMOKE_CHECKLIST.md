# Cleanup Smoke Checklist

Run this checklist after local refactor batches. Do not commit/push unless explicitly requested.

## Python Checks

- `& "$HOME\anaconda3\python.exe" -m py_compile fs_sweep_app_spline.py preselection_shortlist.py`
- `& "$HOME\anaconda3\python.exe" -m pyflakes fs_sweep_app_spline.py preselection_shortlist.py`

## App Startup

- Start app with `run_app.bat`.
- Confirm local `FS_sweep.xlsx` loads.
- Confirm upload path still loads an `.xlsx` file.

## Core Context Switches

- Switch `Positive` / `Zero`.
- Switch base frequency `50 Hz` / `60 Hz`.
- Switch location.
- Toggle spline on/off.

## Plot Visibility

- Toggle `R vs X scatter`.
- Toggle `X`, `R`, `X/R`.
- Toggle `Selection mode`.
- Confirm default layout still stacks scatter then line plots.
- Confirm selection mode row 1 is scatter + `X`; row 2 is `R` + `X/R`.

## Selection / Filters

- Use case-part filters.
- Change color mode.
- Click scatter point; selected point becomes `diamond`.
- Click line trace; same case selection updates.
- Toggle `Show only selected sweeps`.
- Import case list with spaces, commas, tabs, and newlines.
- Remove selected row with `Del`.
- Clear selected list.
- Download selected CSV.

## Methods / Harmonics

- Toggle Energinet.
- Edit `T2`, `T3`, `T4`.
- Set Energinet `Top N`.
- Toggle IEC.
- Set IEC `Top N`.
- Toggle `Include collinear boundary (+N)`.
- Toggle harmonic lines.
- Change bin width.

## Scatter Frequency

- Move in-plot slider.
- Use `Prev frequency` / `Next frequency`.
- Use `Set f (Hz)`.
- Confirm scatter status count and frequency steps update.

## Export

- Export `X`, `R`, and `X/R` PNG when enabled.
- Confirm selected-only legend state is reflected in export.
