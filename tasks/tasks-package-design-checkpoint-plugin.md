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
  - [x] 4.4 Make the case-variant dependency fixtures portable to
    case-insensitive macOS filesystems and re-run the PR matrix.
  - **Validates when:**
    - `make check` exits zero.
    - The current Open Design integration proves both plugin-local skills and
      helpers are active/staged.
    - `git diff --check` exits zero.
    - Ubuntu and macOS matrix jobs pass for Python 3.10 and 3.14.

- [x] 4.5 Align the paired plugin icon semantics <!-- Serves: AC-1, AC-7 -->
  - [x] 4.5.1 Preserve the checkpoint SVG byte-for-byte.
  - [x] 4.5.2 Derive the handoff SVG from the checkpoint composition: retain
    the navy background, mint frame, and unmoved amber inner shape; remove the
    coral dot; close the frame's right side with aligned mint geometry.
  - [x] 4.5.3 Render both SVGs side by side and at small sizes, validate the
    SVG resources, and publish the focused update to PR #4.
  - **Validates when:**
    - The checkpoint asset checksum is unchanged.
    - The handoff asset shares the checkpoint view box, background, mint/yellow
      geometry, and accessible-title structure; only its final-state closure
      and absence of the coral dot differ.
    - The pair remains legible at plugin-card and native sizes.

- [x] 4.6 Address owner and PR-review follow-up <!-- Serves: AC-1, AC-3, AC-4, AC-7, AC-10 -->
  - [x] 4.6.1 Rebuild the handoff mint geometry as a uniform complete square
    outside the checkpoint frame's open edge, without moving the amber shape.
  - [x] 4.6.2 Expand both fail-closed credential detectors and their controls
    across case, separators, bare names, and common text/config suffixes.
  - [x] 4.6.3 Reject ordinal-only target labels across numbered, lettered,
    Roman-numeral, and bare role forms while preserving descriptive labels.
  - [x] 4.6.4 Record the owner's direct scope ratification, reconcile review
    comment `5179218280`, run the full validation surface, and update PR #4.
  - **Validates when:**
    - The handoff frame has uniform 14 px mint sides, preserves the checkpoint
      icon and amber path byte-for-byte, omits coral, and reads as a square at
      native and 32 px sizes.
    - Both production CLIs reject the review counterexamples plus adversarial
      case/separator/suffix variants before publishing an archive.
    - Exact exclusions and handoff reviewed inclusions remain positive controls.
    - Generic positional labels fail and descriptive state/role labels pass.
    - Local checks, the pinned Open Design contract, and hosted PR checks pass.

- [x] 4.7 Close exact-head scope and spelled-position review findings <!-- Serves: AC-1 through AC-10 -->
  - [x] 4.7.1 Bind AC-1 through AC-10 to the owner's durable ratification
    comment `5183292830` and remove self-ratifying authority claims.
  - [x] 4.7.2 Reject role-only spelled cardinal and ordinal positions while
    preserving genuinely descriptive target labels.
  - [x] 4.7.3 Run focused production-CLI regressions, the complete local
    validation surface, independent phase-gate review, and hosted PR checks.
  - **Validates when:**
    - The PRD links the exact owner-authored comment that approves the complete
      checkpoint contract and AC-1 through AC-10.
    - Production dry-runs reject `Option One`, `Alternative First`, and
      `Variant Two` but accept descriptive controls.
    - `make check`, pinned Open Design integration, `git diff --check`, and the
      hosted matrix pass on the published head.

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

### Task 4.4 CI Follow-up Preflight

- Validation plan written: yes
- Validation plan saved in artifact: yes
- Validation review mode: auto-proceed
- Canonical command surface identified: yes (`make check` and
  `make integration-open-design`)
- Acceptance criteria served by this task listed: yes (AC-10)
- Relevant failing tests and GitHub Actions logs read before modification: yes

**Pre-implementation validation plan:**

1. Preserve the case-variant exclusion assertion while making fixture creation
   deterministic on case-sensitive and case-insensitive filesystems.
2. Run `make check`, the pinned Open Design integration, and
   `git diff --check` locally.
3. Publish the focused fix and require all Ubuntu/macOS Python matrix jobs to
   pass before restoring Task 4.0 to complete.

### Task 4.5 Paired Icon Preflight

- Validation plan written: yes
- Validation plan saved in artifact: yes
- Validation review mode: auto-proceed; the owner supplied exact visual deltas
  and explicitly requested publication to the existing PR.
- Canonical command surface identified: yes (`make check`, SVG XML/resource
  validation, side-by-side visual rendering, and `git diff --check`)
- Acceptance criteria served by this task listed: yes (AC-1, AC-7)
- Existing paired SVG assets and repository visual-consistency rules read before
  modification: yes

**Pre-implementation validation plan:**

1. Record the checkpoint SVG checksum and leave the file untouched.
2. Apply only the approved semantic delta to the handoff SVG.
3. Render the pair together and at small size; inspect alignment, color,
   closure, and legibility.
4. Run repository validation and diff checks, then update PR #4 and
   confirm its checks.

### Task 4.6 Review Follow-up Preflight

- Validation plan written: yes
- Validation plan saved in artifact: yes
- Validation review mode: auto-proceed; the owner requested all appropriate
  review fixes and explicitly authorized updating the existing PR branch.
- Canonical command surface identified: yes (`make check`,
  `make integration-open-design`, SVG render inspection, adversarial CLI
  controls, `git diff --check`, and hosted PR checks)
- Acceptance criteria served by this task listed: yes (AC-1, AC-3, AC-4,
  AC-7, AC-10)
- PR metadata, top-level feedback, thread state, current helpers/tests, icon
  geometry, and current Rule 9 read before modification: yes

**Pre-implementation validation plan:**

1. Preserve the checkpoint SVG and amber path checksums; replace the inward
   handoff closure with a single seam-free uniform outer ring.
2. Add red-first credential and label counterexamples from the review plus
   broader case/separator/suffix and ordinal-form matrices.
3. Implement the narrowest shared behavior that closes those counterexamples
   without weakening exact-review controls or descriptive labels.
4. Render the icon pair at native and small sizes, run narrow regressions,
   `make check`, pinned Open Design integration, secret/diff audits, and an
   independent phase-gate review before publication.
5. Update PR #4 by normal fast-forward only and require its complete hosted
   matrix to pass.

### Task 4.7 Exact-Head Review Preflight

- Validation plan written: yes
- Validation plan saved in artifact: yes
- Validation review mode: auto-proceed; the owner requested all remaining
  review fixes and explicitly authorized updating PR #4.
- Canonical command surface identified: yes (`make check`,
  `make integration-open-design`, focused production-CLI controls,
  `git diff --check`, and hosted PR checks)
- Acceptance criteria served by this task listed: yes (AC-1 through AC-10)
- Latest exact-head review, owner ratification comment, current classifier,
  tests, PRD, task state, and current Rule 9 re-read before modification: yes

**Pre-implementation validation plan:**

1. Add production-level negative controls for spelled cardinal/ordinal
   role-only labels and positive controls for descriptive labels.
2. Run the focused tests before implementation and confirm they fail only on
   the missing spelled-position behavior.
3. Implement a bounded deterministic word-position classifier, link the exact
   owner-ratification comment from the PRD, and reconcile PR wording/state.
4. Run focused tests, `make check`, pinned Open Design integration,
   `git diff --check`, sensitive-data inspection, and independent phase-gate
   review.
5. Push PR #4 normally, update its description, and require the complete hosted
   matrix and fresh exact-head review to pass.

## Current Status

Tasks 1.0 through 4.7 are implemented and validated. Task 4.7's ratification
binding, classifier change, production regressions, complete local suite,
independent phase-gate reviews, and exact-head hosted matrix all pass. PR #4
remains open and linked to bug report #3; fresh owner review remains.

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

- `make check` — 59 tests passed; one opt-in integration test skipped by the
  default suite as designed.
- `make integration-open-design OPEN_DESIGN_REPO=/workspace/scratch/0b3846b623e4/open-design-current`
  — one production-contract integration passed at exact revision
  `fe1231eed69a2312e56c4e155e06781981fff068`.
- `git diff --check` — passed.
- GitHub Actions run `30909011909` — Open Design contract plus Ubuntu/macOS on
  Python 3.10 and 3.14 all passed.
- GitHub Actions run `30910687979` — the paired-icon commit passed the Open
  Design contract plus Ubuntu/macOS on Python 3.10 and 3.14.
- Paired-icon visual review — checkpoint SHA-256 remained
  `a676e7eb109b66cf0b1f2a191100b35e497abcdbbb3dd01c4f590989b0a877ba`;
  both native and 32 px renders passed with no blocker, major, or minor finding.
- Review follow-up adversarial gates — both production credential classifiers
  passed 26 sensitive and 19 safe-name probes per helper while preserving exact
  controls; the functional-label classifier passed exhaustive canonical Roman
  1–3999 checks plus Unicode, compatibility, ordinal, and descriptive controls;
  neither gate retained a blocker, major, or minor finding.
- GitHub Actions run `30917223702` — Task 4.6's Open Design contract plus
  Ubuntu/macOS on Python 3.10 and 3.14 all passed on head `ea7769a3`.
- Task 4.7 focused production-CLI controls — `Option One`, `Alternative First`,
  and `Variant Two` fail; `Option optimized for keyboard navigation` succeeds
  in the dry-run plan without publishing a ZIP.
- Task 4.7 independent phase gates — ratification binding and spelled-position
  behavior both passed with no publication blocker.
- GitHub Actions run `30941988640` — Task 4.7's Open Design contract plus
  Ubuntu/macOS on Python 3.10 and 3.14 all passed on head `b5e49a1`.

## Reconciliation Audit

- **Blockers:** None in the implementation or validation surfaces.
- **Majors:** None after final security and product-documentation review.
- **Minor:** Open Design's pinned runtime has no restricted, pipeline-free
  packaging-plugin kind. The sidecars intentionally use its pipeline-free
  `scenario` identity case so desktop GitHub imports need only `prompt:inject`;
  re-evaluate when the upstream capability model changes.
- **Info:** Direct Codex execution of the new checkpoint skill is conservatively
  labeled format-compatible until a separate harness-forward test is added.
- **Operational:** The explicitly authorized feature branch, issue #3, and
  PR #4 are published. Rule 9 still does not authorize merge or a direct push
  to `main`.

## Follow-Up Items

- [ ] Re-test the sidecar classification when Open Design supports a
  pipeline-free `skill` without granting `pipeline:*` to restricted imports.
- [ ] Add a direct Codex harness-forward test before upgrading the checkpoint
  catalog label from format-compatible to verified.
