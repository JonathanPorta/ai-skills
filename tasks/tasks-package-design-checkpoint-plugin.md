# Tasks: Package Design Checkpoint Plugin

> Generated from [PRD: Package Design Checkpoint Plugin](prd-package-design-checkpoint-plugin.md)

## Acceptance Criteria Traceability

| AC | Criterion | Tasks |
|---|---|---|
| AC-1 | Complete independently importable checkpoint skill | 1.0 |
| AC-2 | Independent immutable SemVer checkpoint stream | 2.0 |
| AC-3 | Explicit identity and hardened payload boundaries | 2.0 |
| AC-4 | Root index, primary/alternatives, target validation | 2.0 |
| AC-5 | Concise checkpoint-only metadata | 2.0 |
| AC-6 | Private validation, atomic publication, optional SHA | 2.0 |
| AC-7 | Checkpoint/handoff responsibility separation | 1.0, 3.0 |
| AC-8 | First-class Open Design plugin-local loading | 1.0, 4.0 |
| AC-9 | Accurate desktop installation and invocation docs | 3.0 |
| AC-10 | Full repository and current Open Design validation | 4.0 |

## Relevant Files

- `skills/package-design-handoff/` — Existing final-delivery workflow to narrow
  and enrich with a first-class Open Design sidecar.
- `skills/package-design-checkpoint/` — New self-contained interim checkpoint
  workflow and helper.
- `scripts/check_skills.py` — Sidecar and resource validation.
- `tests/test_package_checkpoint.py` — New checkpoint behavioral/security tests.
- `tests/test_package_handoff.py` — Final-handoff and responsibility-boundary
  regressions.
- `tests/test_check_skills.py` — Validator regressions for Open Design sidecars.
- `tests/test_open_design_integration.py` — Production plugin-local loading and
  staging contract.
- `README.md` — Catalog, responsibility table, installation, and update policy.

### Notes

- Run local validation with `make check`.
- Run current Open Design integration through the repository's canonical
  integration target once its pinned revision is updated.
- Both runtime helpers must remain self-contained inside their skill folders.

## Tasks

- [x] 1.0 Define the paired plugin contracts <!-- Serves: AC-1, AC-7, AC-8 -->
  - [x] 1.1 Add the checkpoint skill structure and narrow both descriptions.
  - [x] 1.2 Add sidecars that bind each plugin-local `SKILL.md` at runtime.
  - [x] 1.3 Keep shorthand conversational and make plugin-picker invocation
    explicit.
  - **Validates when:**
    - Both manifests have stable identity/version and local skill paths.
    - Trigger tests distinguish interim checkpoint from final handoff language.

- [x] 2.0 Implement the checkpoint archive contract <!-- Serves: AC-2, AC-3, AC-4, AC-5, AC-6 -->
  - [x] 2.1 Add red-first tests for identity, version stream, index inventory,
    exclusions, credential boundaries, generated metadata, ZIP validation, and
    publication behavior.
  - [x] 2.2 Implement the self-contained checkpoint helper.
  - [x] 2.3 Exclude checkpoint archives from final handoff payloads without
    allowing them to affect handoff version discovery.
  - **Validates when:**
    - Initial and default patch checkpoint tests pass.
    - Broken or unsafe input fails before a public archive appears.
    - The ZIP contains a valid root index and concise checkpoint changelog but
      no generated full-handoff artifacts.

- [x] 3.0 Correct product documentation and preserve evidence <!-- Serves: AC-7, AC-9 -->
  - [x] 3.1 Add the paired catalog and responsibility table.
  - [x] 3.2 Document plugin import, plugin-picker application, manual re-import,
    standalone-agent installation, and the `/usr/bin/od` collision.
  - [x] 3.3 Add relevant supplied screenshots with descriptive filenames and
    captions; omit account/settings evidence unrelated to skill use.
  - **Validates when:**
    - No documentation claims native Open Design slash-command support.
    - No documentation requires a duplicate agent install for an applied
      first-class plugin.
    - No unsupported desktop `od` command is recommended.

- [x] 4.0 Validate the integrated change <!-- Serves: AC-8, AC-10 -->
  - [x] 4.1 Extend sidecar validation and negative tests.
  - [x] 4.2 Exercise plugin-local loading and companion-script staging for both
    skills against current pinned Open Design source.
  - [x] 4.3 Run the full suite, inspect the diff, reconcile every acceptance
    criterion, and prepare one feature commit plus PR text.
  - **Validates when:**
    - `make check` exits zero.
    - The current Open Design integration proves both plugin-local skills and
      helpers are active/staged.
    - `git diff --check` exits zero.

### Task 1.0 Preflight

- Validation plan written: yes
- Validation plan saved in artifact: yes
- Validation review mode: auto-proceed; the owner supplied the complete minimum
  contract and explicitly requested implementation.
- Canonical command surface identified: yes (`make test`, `make check`, and the
  existing Open Design integration target)
- Acceptance criteria served by this task listed: yes
- Relevant files and current Open Design runtime paths read before modification:
  yes

**Pre-implementation validation plan:**

1. Add failing tests for the new checkpoint behavior and sidecar runtime binding.
2. Implement the smallest self-contained helpers and manifests that satisfy the
   approved contract.
3. Run narrow tests during implementation, then the full repository and current
   Open Design integration surfaces.
4. Audit documentation claims and final diffs against every acceptance
   criterion before preparing publication artifacts.

## Current Status

Tasks 1.0 through 4.0 are implemented and validated. The local branch is ready
for the explicitly authorized feature-branch push and owner review through a
pull request.

## Acceptance Criteria Verification

| AC | Evidence | Status |
|---|---|---|
| AC-1 | Collection validator recognizes both self-contained skill/plugin subtrees and their executable helpers. | MET |
| AC-2 | Checkpoint tests cover initial `0.1.0`, default patch increments, immutable prior bytes, identity collisions, and handoff-stream independence. | MET |
| AC-3 | Security regressions cover explicit identity, namespace separation, VCS/dependency/caches, symlinks, portable paths, and JSON/YAML/YML/TOML credential names. | MET |
| AC-4 | Tests cover generated/existing HTML and Markdown indexes, mixed targets, every browsable mockup, functional link labels, `srcset`, unsafe URLs, and missing targets. | MET |
| AC-5 | ZIP assertions require only the root index plus `_checkpoint/CHANGELOG.md` and reject handoff/manifest/checksum metadata. | MET |
| AC-6 | Tests cover private validation, no-clobber publication, preserved archives, and opt-in-only final SHA reporting. | MET |
| AC-7 | Portable descriptions, OpenAI metadata, catalog, decision table, and regressions route interim versus accepted-final work separately. | MET |
| AC-8 | Pinned Open Design integration applies both restricted plugins, loads both local skill bodies, stages both helper directories, and executes both packagers. | MET |
| AC-9 | Root and skill READMEs document plugin installation/application, literal shorthand limits, re-import updates, selected-agent behavior, screenshots, and `/usr/bin/od`. | MET |
| AC-10 | `make check`, pinned `make integration-open-design`, and `git diff --check` all exit zero. | MET |

## Validation Results

- `make check` — 49 tests passed; one opt-in integration test skipped by the
  default suite as designed.
- `make integration-open-design OPEN_DESIGN_REPO=/workspace/scratch/0b3846b623e4/open-design-current`
  — one production-contract integration passed at exact revision
  `fe1231eed69a2312e56c4e155e06781981fff068`.
- `git diff --check` — passed.
- Final adversarial review — prior credential, case-variant exclusion, mockup
  completeness, label association, `srcset`, and URL-encoding findings closed.

## Reconciliation Audit

- **Blockers:** None in the implementation or validation surfaces.
- **Majors:** None after final security and product-documentation review.
- **Minor:** Open Design's pinned runtime has no restricted, pipeline-free
  packaging-plugin kind. The sidecars intentionally use its pipeline-free
  `scenario` identity case so desktop GitHub imports need only `prompt:inject`;
  re-evaluate when the upstream capability model changes.
- **Info:** Direct Codex execution of the new checkpoint skill is conservatively
  labeled format-compatible until a separate harness-forward test is added.
- **Operational:** Checked-in Rule 9 now permits the requested normal
  feature-branch push and pull-request creation after explicit current-session
  authorization. It does not authorize merge or a direct push to `main`.

## Follow-Up Items

- [ ] Re-test the sidecar classification when Open Design supports a
  pipeline-free `skill` without granting `pipeline:*` to restricted imports.
- [ ] Add a direct Codex harness-forward test before upgrading the checkpoint
  catalog label from format-compatible to verified.
