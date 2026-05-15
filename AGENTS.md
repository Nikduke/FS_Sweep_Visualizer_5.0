# AGENTS.md

## General
- These are default working rules. Follow the user's explicit request when it conflicts with them.
- Keep this file short, practical, and focused on durable defaults.

## Working rules
- This workspace is v5 only: `C:\Users\AndreyNikishin\MY_Code\Frequency_sweep_2026_v5_clean`.
- Remote is `git@github.com:Nikduke/FS_Sweep_Visualizer_5.0.git`.
- Do not read, patch, run, commit, or push `C:\Users\AndreyNikishin\MY_Code\Frequency_sweep_2026` unless user explicitly asks.
- Default to minimal, local changes.
- Follow existing code patterns before introducing new abstractions.
- Inspect relevant files first; do not guess APIs, file structure, or behavior.
- Avoid new dependencies unless justified by the task.
- Preserve existing behavior unless a change is required.
- Prefer simple, maintainable solutions over clever or oversized ones.
- When several valid approaches exist, prefer the one with less code, less complexity, and less maintenance cost.

## Skills
- Use `$caveman` for tasks focused on simplification, reducing code, removing unnecessary abstractions, avoiding overengineering, finding the smallest correct implementation, and keeping responses strict, concise, and specific.
- Skill path: `C:\Users\AndreyNikishin\.agents\skills\caveman\SKILL.md`
- Do not force `$caveman` for unrelated tasks.

## Validation
- Run the most relevant checks for touched code when practical.
- If no clear validation command is available, inspect the existing project files and use the most appropriate available method.
- If a check cannot be run, say so explicitly.

## Communication
- Answer only what was asked.
- Be direct, strict, and specific.
- Keep answers concise.
- Do not give long explanations unless explicitly requested.
- Do not repeat information already given.
- Do not add unnecessary background, caveats, or summaries.
- Keep progress updates brief and only when something materially changed.
- Prefer short bullet points over long prose.

## Final response
- Include only:
  1. result
  2. files changed
  3. checks run
  4. open issues or assumptions
