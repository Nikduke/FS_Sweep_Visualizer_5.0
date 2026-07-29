# AGENTS.md

## Project Scope

This folder is the active FS Sweep Visualizer project root.

This is a Git repository. Preserve unrelated worktree changes, inspect `git status -sb` before editing, and do not use destructive Git commands unless explicitly requested.

## Before Editing

- Read `README.md`, `SETUP_CONDA.md`, and `PROJECT_CONTEXT.md`.
- Inspect relevant code before making claims.
- Report understanding before changing files when task is non-trivial.

## Environment

- Use conda environment `fs-sweep-visualizer`.
- Do not use conda `base` for project work.
- See `SETUP_CONDA.md` for setup commands.

## Working Rules

- Make small targeted changes.
- Prefer simple local fixes over new abstractions.
- Do not rewrite working code for style only.
- Avoid new dependencies unless clearly required.
- Keep documentation paths relative.
- Update relevant documentation after meaningful code changes.
- Do not copy in old backups, historical folders, or generated caches.

## Validation

Run the smallest relevant checks after edits:

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

## Final Response Style

Include:

1. result
2. files changed
3. checks run
4. open issues or assumptions
