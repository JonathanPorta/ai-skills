# Plan: consolidate notes trackers onto the tracker skill

Reusable migration guidance. Track project-specific ownership, rollout order,
counts, and completion evidence in the consuming notes repository. This document
is not a live migration tracker.

## Existing tracker families

| Family | Shape | Migration consideration |
|---|---|---|
| Canonical | Schema 2, six stage indicators | Preserve rendered output except intentional configurable captions. |
| Renamed stage | Schema 2 with a renamed third-stage key | Normalize the key to `issues`; retain the display label in configuration. |
| Older | Schema 1, `planning` stage | Recover field names and template-carried text before conversion. |
| Custom layout | Computed geometry and multiple evidence URLs | Preserve design until an explicit migration choice; never discard evidence. |
| Shared loader | HTML reads neighboring SVG/state files | Preserve offline behavior and the combined viewer's bundling adapter. |

## Target

- One reusable renderer in the skill. Tracker directories hold configuration,
  structured state, their README, and rendered views.
- Schema 2 for trackers intentionally migrated to the shared design; independent
  stage values and per-project display labels remain intact.
- Every included tracker has a resolvable source revision in its combined viewer.
- Changes use isolated task worktrees and reviewable PRs.

## Migration sequence

1. Install or locate a reviewed skill revision using the agent's configured skill
   path. Record that revision with the migration evidence.
2. Rehearse on one canonical tracker. Compare SVG/HTML before and after, explain
   intended differences, update refresh commands, and rebuild its configured hub.
3. Convert renamed-stage trackers with `issues_label` and `issues_note` settings;
   retain the old stage meaning. Review both state and rendered output.
4. Convert older schemas with the skill's migration helper. Keep extra notes and
   source links in the README when the schema cannot represent them directly.
5. Review custom geometry and loader-based designs separately. Do not assume a
   shared design is authorized merely because a shared renderer exists.
6. Remove copied renderers only after the replacement passes visual and data
   checks. Retain required adapters until their last consumer has migrated.

For each tracker, record source revision, artifacts, validation, unresolved
questions, and acceptance in its own notes. Migration completion is distinct from
completion of the project that tracker describes.

## Hub and publication considerations

Configure local and companion repositories explicitly. Source pins must continue
resolving after the chosen merge strategy; until a hub supports post-merge pin
reconciliation, preserve the commits it references. Follow the current tracker
skill's publication instructions and do not infer authority to merge.

## Verification

- State matches the observed source evidence and retains independent stages.
- `render_tracker.py --check` passes for the selected configuration.
- Visual comparison explains intentional changes; images and README agree.
- Combined-viewer build succeeds against the actual configured sources.
- Source pins are resolvable and secrets are absent.
- Remaining exceptions have an owner and a continuation location.
