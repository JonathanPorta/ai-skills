# Canonical package entrypoint (issue #5)

## Scope and codebase analysis

Implement https://github.com/JonathanPorta/ai-skills/issues/5 in its own branch.
Both packagers currently preserve source at archive root, and checkpoint reuses
an existing launcher or generates bare HTML/Markdown. Existing source-read code
uses archive_path, so source paths must be separated when adding the new layout.
Use the existing standard-library tests and `make check` command surface.

## UX brief and layout decision

Recipient: a reviewer or implementer opening a ZIP for the first time. They need
to identify the package, know what to open, and distinguish review work from
deployment material without guessing. Use one prominent primary link and the
issue's eight sections in order. Render empty decisions explicitly, reported
verification separately from package checks, and conservative deployment defaults.
Use neutral system typography, responsive spacing, semantic headings, and visible
visited/hover/focus states. No scripts, external fonts, or network resources.

Preserve the complete authored payload under `project/` with unchanged relative
paths and bytes. Generate root index.html, README.md, artifact-manifest.json,
and _package/verification.json. Preserve the existing _checkpoint or _handoff
metadata at package root. This intentionally replaces the old root-overlay layout;
both skill/plugin versions become 0.2.0. Prior ZIPs remain immutable.

## Acceptance and validation

1. Both variants always generate root index.html, with all eight issue sections.
2. The root README starts **Open `index.html` first.** and shares normalized metadata.
3. All declared local links resolve; a primary target is required; inputs cannot
   inject external links, scripts, or markup into the guide.
4. Every root entry and source top-level entry is mapped; empty decisions,
   blockers, and withheld lists display None.
5. Checkpoints are review-only. Handoffs require explicit deployment claims and
   a scoped subtree. Caller verification defaults not-run; pass/fail needs evidence.
6. Source index.html/README and relative links remain intact under project/.
7. Existing credential, symlink, portable namespace, versioning, and atomic ZIP
   publication protections remain enforced. Handoff checksums include new metadata.
8. Unit fixtures cover both packagers, metadata errors, title deduplication, offline
   HTML, collisions, empty states, and source preservation. Run `make check` and
   render representative guides at narrow/wide viewports for visual inspection.
9. Update skill docs, helper usage, manifests, and staged-plugin smoke test.
   Actual desktop reinstall after release remains a user-host follow-up; do not
   claim it from this environment or block the requested PR on that later step.

## Shared renderer interface

Ship byte-identical `scripts/package_index.py` in both independently installable
skills, guarded by a parity test. Import it by a path-safe local module mechanism.

`load_metadata(path)` reads an optional UTF-8 JSON object; None returns {}.

`build_index(*, project_name, slug, artifact_type, version, change, payload_paths,
primary, review_targets=(), metadata=None, namespace=None, created_at=None,
docs=()) -> dict[str, bytes]` returns the four generated files above. artifact_type
is checkpoint or handoff; version is a string; payload_paths are original
project-relative FILE paths (before project/ prefix). primary is None or
{path,label,description?}; review_targets are the same with optional role
(default alternate). docs are {path,label,description?} for known generated
root-relative metadata files, e.g. _checkpoint/CHANGELOG.md or _handoff/MANIFEST.json.

Metadata supports primary, review_targets, review_checklist (strings), decisions,
blockers, withheld (string arrays), lifecycle (string), package_map
({path,role,description} source-relative rows), verification
({status:not-run|passed|failed,summary,evidence? source-relative file}), deployment
({posture:review-only|implementation-ready|deployable,path? source-relative directory,
description?}). Metadata primary/review descriptions may enrich CLI targets, but
conflicting primary paths fail. No primary => error. Default description explains
the supplied label; default checklist asks reviewer to inspect primary/alternatives.
Checkpoint deployment is always review-only; handoff defaults review-only until
caller declares otherwise. Deployable posture requires a real payload directory,
no outstanding decisions/blockers/withheld items, and reported passed verification
with evidence. Report verification as caller-reported; package checks are distinct.
Reject unknown fields to catch metadata mistakes.

`validate_index(generated, archive_names)` validates generated root links and
metadata/map coverage. Call before dry-run completion and against bytes read from
the private ZIP before publishing. Include caller docs in expected archive names.
The helper's existing CRC/source hash verification must still pass before the
generated packaging PASS report can be published. Do not claim project tests ran.

## Parallel ownership and validation plan

- Renderer: the two package_index.py copies plus tests/test_package_index.py.
- Checkpoint: its main helper and tests/test_package_checkpoint.py.
- Handoff: its main helper and tests/test_package_handoff.py.
- Integration/docs: root owner handles skill docs, reference examples, versions,
  README catalog, tests/test_open_design_integration.py, render QA, and publication.

Use focused tests per independent task; then run `make check` once integrated.
Create one PR from jp/f/package-root-index against main. Do not merge or reinstall
the user's desktop skills as part of this authoring step.
