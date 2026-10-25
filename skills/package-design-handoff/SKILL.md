---
name: package-design-handoff
description: Package an accepted OpenDesign or other design project into an immutable, complete, implementation-ready handoff ZIP. Use for final delivery, complete source and asset transfer, implementation specifications, or revisions to an existing final handoff. Do not use for interim review, comparisons, state explorations, or alternate directions; route those to package-design-checkpoint.
---

# Package Design Handoff

Create the archive as part of completing the accepted design task. Do not merely
remind the user to request one. `/handoff` is conversation shorthand, not a
literal Open Design slash command.

## Workflow

1. Confirm the final project directory and actual human-readable project name.
   Ask when either is genuinely ambiguous; never substitute a page or mockup
   name for project identity.
2. Confirm the work is accepted and needs a complete implementation-ready
   delivery. For interim review, comparison, state exploration, alternate
   directions, or resumption, use `package-design-checkpoint` instead.
3. Finish the requested design work before packaging. Do not change accepted
   design truth merely to make the archive cleaner.
4. Treat “everything” as every project-authored final deliverable: editable
   sources, exports, prototypes, raster assets, icons, tokens, code, fixtures,
   fonts or sonic assets that may legally ship, specifications, implementation
   notes, and relevant provenance. Exclude version-control internals, dependency
   trees, disposable caches, OS metadata, temporary files, earlier handoff ZIPs,
   and recognized versioned checkpoint ZIPs. Credential-like files
   fail closed unless their exact project-relative path is reviewed for
   exclusion or explicit inclusion. Preserve the authored tree intact under
   `project/` in the ZIP, including its original index and README. The root is
   reserved for the package guide and metadata; it is not a deployment root.
5. Select the SemVer increment without asking when the task provides enough evidence:
   - Initial: `0.1.0` when no prior archive exists.
   - Patch: corrections, refinements, regenerated exports, or completion of the same promised scope.
   - Minor: a new screen, direction, asset family, deliverable category, meaningful additive scope, or an incompatible pre-1.0 restructuring.
   - Major: an incompatible restructuring after 1.0 or an explicit major-version request.
6. Write a brief bump reason that says what changed. Never overwrite or mutate a
   prior archive. Choose one primary preview or implementation document and
   prepare [package metadata](references/package-metadata.md) with descriptions,
   review steps, decisions/blockers, withheld items, package-map annotations,
   acceptance status, and truthful verification evidence. Set implementation-ready
   posture only for accepted work. Declare a deployable subtree only when that
   precise subtree is approved and verified; never infer it from the ZIP type.
7. Locate `scripts/package_handoff.py` in this skill directory. In an Open
   Design plugin run, the directory is staged under the project-local
   `.od-skills/` tree; if its path is not supplied in the prompt, locate the
   single staged `package-design-handoff-*/scripts/package_handoff.py` file
   there. Do not substitute a manually recreated ZIP. Run:

   ```bash
   python3 /path/to/package-design-handoff/scripts/package_handoff.py \
     /path/to/project \
     --project-name "Human Project Name" \
     --primary index.html "Accepted responsive website" \
     --package-metadata /path/outside/project/package-metadata.json \
     --bump patch \
     --bump-reason "Corrected responsive states and completed icon exports"
   ```

   Supply `--primary TARGET LABEL` or a primary in metadata; missing primary is an
   error. Use source-relative paths in metadata and CLI targets, without the
   generated `project/` prefix. Use `--output-dir` when archives belong elsewhere.
   Use repeatable `--exclude` globs only for intentional project-specific exclusions.
   Use `--version X.Y.Z` instead of `--bump` only when the next version is fixed.
8. Trust completion only after the helper validates the private ZIP, publishes it atomically, and prints its SHA-256. If the helper fails because of an unresolved symlink, credential boundary, non-portable name, reserved metadata collision, missing payload, non-monotonic version, or existing destination, fix the cause; do not bypass the guardrail.
9. Return the archive itself or a clickable link, plus its exact filename, version,
   payload-file count, and SHA-256. Tell the recipient to open root `index.html`
   first. Briefly name intentional exclusions. Do not claim the handoff is complete
   if the archive is unavailable.

## Archive contract

- Name new archives `<project-slug>-<MAJOR.MINOR.PATCH>.zip`; use lowercase ASCII kebab-case and no `v` prefix.
- Discover both canonical and legacy `-vX.Y.Z.zip` archives when calculating the next version, but emit only the canonical form.
- Preserve source bytes and relative paths under `project/`. Skill version 0.2.0
  replaces the previous archive-root overlay layout. Deploy only an explicitly
  approved subtree, never the packaging root.
- Always generate root `index.html`, `README.md`, `artifact-manifest.json`, and
  `_package/verification.json`. Derive the guide and README from the same data.
  Start the README with **Open `index.html` first.**.
- Present identity, start here, changes, review steps, decisions/blockers, package
  map, verification, and documentation in that order. Render empty decisions as
  None. Use styled responsive HTML, relative links, and no scripts or network
  dependencies. Preserve the original project preview instead of replacing it.
- Add `_handoff/README.md`, `_handoff/MANIFEST.json`, and `_handoff/CHECKSUMS.sha256` inside the ZIP without modifying the source directory.
- List every payload file with its size and SHA-256 in the handoff manifest,
  distinguish generated packaging files, and include them in checksum validation.
  Record previous version, bump type, bump reason, and intentional exclusions.
- Keep project verification `not-run` unless supplied evidence establishes a
  reported pass/fail. Packaging success is not proof that project tests ran.
- Sort archive entries and validate their names, bytes, checksums, manifest, and ZIP CRC before reporting success.

Example: if `dont-make-me-think-adaptive-interface-0.2.1.zip` exists, a refinement becomes `dont-make-me-think-adaptive-interface-0.2.2.zip`.
