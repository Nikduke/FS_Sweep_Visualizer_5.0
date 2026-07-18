# Starter Prompt for Codex on New Laptop

You are working in this folder as the active project root. Treat this project as not using Git unless I explicitly say otherwise.

First read:

1. `README.md`
2. `SETUP_CONDA.md`
3. `PROJECT_CONTEXT.md`
4. `CLEANUP_SMOKE_CHECKLIST.md`

Then inspect the actual codebase before making claims or edits.

Use Anaconda Python with the dedicated conda environment `fs-sweep-visualizer`. Do not use the base environment. If the environment does not exist, create it with:

```powershell
conda env create -f environment.yml
conda activate fs-sweep-visualizer
```

Before editing files, report your understanding of:

- app purpose;
- active entry point;
- relevant files for the requested task;
- checks you plan to run.

Rules:

- Use only relative paths in project documentation.
- Make small targeted changes.
- Avoid broad rewrites.
- Avoid unnecessary abstractions.
- Avoid style-only rewrites of working code.
- Preserve working behavior unless change is explicitly required.
- Update relevant documentation after meaningful changes.
- Run the smallest relevant checks after edits.
- If documentation conflicts with code, trust code and update documentation.
