# PRD: Package Design Checkpoint Plugin

## Summary

Add a self-contained `package-design-checkpoint` Agent Skill and make both the
checkpoint and existing handoff workflows first-class Open Design plugins. A
checkpoint preserves the current design state for review or resumption without
claiming final implementation readiness; a handoff remains the complete final
delivery.

## Codebase Analysis

### Explored

- `skills/package-design-handoff/SKILL.md` — Defines the existing complete,
  implementation-ready handoff workflow.
- `skills/package-design-handoff/scripts/package_handoff.py` — Provides hardened
  SemVer discovery, credential and symlink boundaries, portable ZIP names,
  private validation, and atomic no-clobber publication.
- `skills/package-design-handoff/README.md` — Documents GitHub import, the
  desktop update path, local-agent installation, and direct helper use.
- `scripts/check_skills.py` — Validates skill structure, metadata, resources,
  Python syntax, and generic JSON syntax.
- `tests/test_package_handoff.py` — Covers packaging, credential, Unicode,
  symlink, ZIP-integrity, publication-race, and documentation contracts.
- `tests/test_open_design_integration.py` — Exercises the older global-skill
  discovery and staging path against a pinned Open Design revision.
- Open Design `fe1231eed69a2312e56c4e155e06781981fff068` — Confirms that a
  GitHub-imported plugin loads its local skill body and stages companion files
  only when `open-design.json` declares
  `od.context.skills[{"path":"./SKILL.md"}]`.
- User-provided Open Design screenshots — Show that the earlier
  `SKILL.md`-only plugin could appear installed without binding its complete
  workflow. Current supported application paths are the Plugins picker, card
  **Use** action, and selecting the installed result from the `@` picker's
  **Plugins** section; literal shorthand text is not an invocation.

### Relevant Patterns

- Every skill is an independently importable `skills/<skill-name>/` subtree.
- Runtime helpers use only the Python standard library and must remain inside
  the skill directory because Open Design imports a GitHub subpath in isolation.
- Initial package versions start at `0.1.0`; subsequent default changes use a
  patch bump.
- Archives are built privately, validated, and published atomically without
  overwriting an existing destination.
- Harness-specific metadata stays beside the portable `SKILL.md` contract.

### Constraints Discovered

- `compat.agentSkills` advertises portability but does not activate a
  plugin-local skill in Open Design.
- Open Design has no plugin-manifest field for a slash alias. `/checkpoint` and
  `/handoff` can only be documented conversational shorthand.
- A non-scenario plugin without a pipeline inherits a bundled pipeline by task
  kind. At the pinned runtime, these packaging plugins therefore use the
  pipeline-free `od.kind: "scenario"` identity case to keep the injected Agent
  Skill as the sole workflow. This is an intentional compatibility workaround:
  declaring a custom pipeline would require `pipeline:*`, which restricted
  GitHub imports do not receive through the desktop apply flow.
- Restricted GitHub imports receive `prompt:inject` by default. Declaring
  elevated capabilities would block the desktop apply flow; the selected local
  execution agent continues to govern its own file and subprocess tools.
- The packaged macOS app does not install Open Design's source-checkout CLI on
  `PATH`; `/usr/bin/od` is the unrelated Unix octal-dump utility.
- Repository Rule 9 permits a normal feature-branch push and pull-request
  creation when the owner explicitly authorizes them in the current session;
  it still requires separate exact authorization for merge, force-push, or a
  direct push to `main`.

### Owner-Confirmed Requirements

These requirements were supplied and explicitly ratified by JonathanPorta in
the interactive owner session on 2026-08-04. The
[PR #4 owner-ratified scope](https://github.com/JonathanPorta/ai-skills/pull/4#owner-ratified-scope)
is the durable review record for that decision; branch-authored planning
artifacts are implementation traceability, not the source of authority.

- Name the pair `package-design-checkpoint` and `package-design-handoff`.
- Use `/checkpoint` and `/handoff` as shorthand while accurately documenting
  that Open Design runs them as plugins, not native slash commands.
- Use the actual Open Design project name as canonical package identity and
  keep an optional namespace as separate metadata.
- Preserve immutable SemVer archives, use patch as the default increment, and
  retain prior archives.
- Include all current project-authored mockups and required local assets, plus a
  root index, one primary target, functionally labeled alternatives, and a
  concise changelog.
- Fail closed on likely credentials; exclude VCS data, dependencies, caches,
  and prior checkpoint archives.
- Validate ZIP readability and every local index target; optionally report one
  final ZIP SHA-256.
- Do not generate an implementation specification, exhaustive component
  inventory, internal checksum manifest, CI/CD evidence, or full implementation
  handoff from the checkpoint workflow.
- Add the supplied Open Design screenshots to the documentation where useful.
- Use paired icon semantics: checkpoint remains an open mint package with the
  amber partial package and coral status dot; handoff is the same composition
  with the amber geometry unmoved, the dot removed, and the mint package closed
  as a visually complete, uniformly weighted square.

### Implementation Choices for Owner Review

- Checkpoints use `<project-slug>-checkpoint-X.Y.Z.zip`; final handoffs retain
  `<project-slug>-X.Y.Z.zip`, so their version streams cannot affect each other.
- The first checkpoint is `0.1.0`, matching the established repository
  convention; every later unspecified increment is a patch.
- The root index is generated from explicit `--primary TARGET LABEL` and
  repeatable `--alternative TARGET LABEL` declarations unless a valid matching
  root index already exists.
- `_checkpoint/CHANGELOG.md` is the checkpoint's only generated internal
  metadata file, avoiding collision with a project-authored root changelog.

## Background

The existing repository has one hardened final-handoff skill. Open Design can
import its `SKILL.md` directory and display a plugin card, but the minimal
adapter does not bind that local skill into a run. That explains the observed
failure where the selected Codex session reports the handoff skill as missing
even though Open Design lists an installed plugin.

The product also needs a lighter interim artifact. Designers routinely need to
freeze prototypes, state explorations, alternate directions, and nonvisual
design material for review or later resumption without generating final
implementation documentation or claiming that delivery is complete.

## Goals

- Add a self-contained checkpoint workflow with an independent archive and
  version namespace.
- Make both workflows load and stage their bundled helpers when applied from
  Open Design's Plugins picker.
- Make checkpoint versus handoff selection obvious and mechanically testable.
- Preserve the handoff helper's existing safety and atomic-publication posture.
- Document real desktop installation, invocation, refresh, local-agent, and
  `/usr/bin/od` behavior without unsupported commands.

## Non-Goals

- Register literal `/checkpoint` or `/handoff` commands in Open Design.
- Generate final implementation documentation or provenance in checkpoints.
- Add a collection-level package manifest or duplicate skills per harness.
- Change Open Design itself or promise compatibility beyond the exact revision
  exercised by integration tests.
- Merge a pull request, force-push, publish directly to `main`, or change
  repository publication policy.

## Architecture & Approach

- Add `skills/package-design-checkpoint/` with portable instructions, OpenAI
  metadata, icon, Open Design sidecar, self-contained Python helper, and README.
- Add `open-design.json` to both skills. Each sidecar points both
  `compat.agentSkills` and `od.context.skills` at `./SKILL.md`, uses the
  `tune-collab` task kind, suppresses unrelated fallback pipelines, and requests
  only `prompt:inject`.
- Fork only the proven safety primitives needed by the checkpoint helper so a
  GitHub-subpath import remains self-contained. Generate a root index and a
  concise `_checkpoint/CHANGELOG.md`, then validate declared and discovered
  local index targets against the private ZIP.
- Keep final handoff metadata unchanged and exclude checkpoint archives from a
  final handoff payload so versioned packages do not recursively nest.
- Extend repository validation to enforce sidecar identity, SemVer, local path
  containment, portable-skill declaration, and Open Design runtime binding.
- Add behavioral tests for checkpoint identity, versioning, navigation,
  exclusions, credentials, metadata boundaries, ZIP validation, SHA reporting,
  and atomic publication.
- Update root and skill-local documentation, including the supplied screenshots
  that demonstrate the plugin-versus-typed-skill distinction.

## Acceptance Criteria

- [x] AC-1: `skills/package-design-checkpoint/` is independently importable and
  contains `SKILL.md`, README, OpenAI metadata, icon, `open-design.json`, and an
  executable standard-library Python helper.
- [x] AC-2: A first checkpoint is named
  `<exact-project-slug>-checkpoint-0.1.0.zip`; a subsequent default run selects
  the next patch without mutating prior archives or consulting handoff versions.
- [x] AC-3: The checkpoint helper requires an explicit project name, keeps the
  namespace separate, packages current project-authored content, excludes VCS,
  dependencies, caches, and prior checkpoint packages, and fails closed on
  symlinks and unreviewed credential-like files.
- [x] AC-4: Every checkpoint contains `index.html` for multiple browsable HTML
  targets or `index.md` for a non-browser checkpoint, identifies one primary
  target, functionally labels every alternative, and fails when any declared or
  local index target is absent from the final ZIP.
- [x] AC-5: A checkpoint generates only `_checkpoint/CHANGELOG.md` metadata and
  does not generate a handoff manifest, internal checksum inventory,
  implementation spec, exhaustive component inventory, or CI/CD evidence.
- [x] AC-6: The helper validates the private ZIP before atomic no-clobber
  publication and prints exactly one final SHA-256 only when requested.
- [x] AC-7: The checkpoint and handoff descriptions, docs, and tests route
  interim review/resumption to checkpoint and accepted implementation-ready
  delivery to handoff without overlapping generic export/archive triggers.
- [x] AC-8: Both sidecars declare their local `SKILL.md` under
  `od.context.skills`; current Open Design loads each body and stages its bundled
  helper when the plugin is applied, with no second local-agent skill install
  required for that Open Design run.
- [x] AC-9: Documentation says to invoke the workflows from Open Design's
  Plugins picker, identifies `/checkpoint` and `/handoff` as nonliteral
  shorthand, explains manual re-import updates and no background polling, and
  warns that `/usr/bin/od` is not Open Design's CLI.
- [x] AC-10: `make check`, the current Open Design integration target, and
  `git diff --check` pass with both skills present.

## Open Questions

- Owner acceptance of the implementation choices is represented by pull-request
  review and merge; no unchecked assumption is treated as previously approved.
- Publication is limited to the explicitly authorized feature-branch push,
  pull-request creation, and related issue; merge remains an owner action.
