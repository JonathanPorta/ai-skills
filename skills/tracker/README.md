# Tracker

Create or refresh a project's evidence-backed tracker in a notes repository.
The shared renderer keeps six independent stage indicators, acceptance gates and
views consistent while project directories hold only state and generated output.

Read [SKILL.md](SKILL.md) for the complete workflow and
[configuration](references/configuration.md) for portable locations and optional
hub inputs. Set a notes checkout explicitly or invoke from that checkout; no
personal paths, project names or agent installation layout are assumed.

## Components

- `scripts/render_tracker.py`: validate and render HTML/SVG, optionally PNG;
  `--check` detects drift from the structured state.
- `scripts/new_tracker.py`: scaffold a new tracker with explicit placeholders.
- `scripts/migrate_tracker.py`: preserve evidence when adopting the shared renderer.
- `scripts/tracker-begin.sh`: create owned task worktrees using `ai-scratch`.
- `scripts/tracker-finish.sh`: render, check, rebuild an optional hub and prepare
  a PR; `--no-push` stops at local commits.
- `scripts/workflow_config.py`: validate repository workflow paths and settings.
- `assets/`: templates, schemas and a generic example.
- `references/evaluation.md`: five-update evaluation using actual handoff quality.

## Validation

Run `make check` from the repository root. Tracker tests cover rendering drift,
invalid inputs, escaping, scaffolding, migration, configurable locations and hub
sources, ownership checks, stale PNG refusal and PR preparation boundaries.
Synthetic checks verify mechanics; evidence review establishes project truth.
