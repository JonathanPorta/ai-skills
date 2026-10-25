---
name: package-design-checkpoint
description: Freeze an in-progress OpenDesign or other design project as an immutable, separately versioned review checkpoint. Use for interim review, comparisons, prototypes, state explorations, alternate directions, or preserving work for later resumption. Do not use for an accepted implementation-ready delivery; route that to package-design-handoff.
---

# Package Design Checkpoint

Create the checkpoint as part of the current design task. `/checkpoint` is
conversation shorthand, not a literal Open Design slash command.

## Workflow

1. Confirm the project directory and the actual Open Design project name. The
   project name is canonical identity. Never infer it from a page, concept,
   current filename, directory name, or generated label. Ask when the actual
   project name is unavailable. Record the Open Design namespace separately
   when one exists; never combine it with or substitute it for project identity.
2. Confirm this is an interim review/resumption package. If the work is accepted
   and needs complete implementation specifications, source provenance, an
   exhaustive deliverable inventory, or final delivery, use
   `package-design-handoff` instead.
3. Inventory every current mockup, prototype, state exploration, alternate
   direction, relevant nonvisual design artifact, and required local asset.
   Choose exactly one primary target. Give every alternative a functional label
   that explains its role or state; labels such as “Alternative 1” are invalid.
4. Prepare the review context using
   [the package metadata contract](references/package-metadata.md). Supply concise
   descriptions, review steps, current decisions/blockers, withheld items,
   package-map annotations, and truthful verification evidence. Keep checkpoint
   deployment posture `review-only`. The helper always generates a polished root
   `index.html`; an authored index remains intact under `project/` and may be the
   primary preview. Never reuse a project page as the package guide.
5. Write one concise `--change` statement. Use a patch bump unless the user
   explicitly fixes another version or the checkpoint series intentionally
   changes scope. The first checkpoint is `0.1.0`; subsequent unspecified runs
   increment the highest checkpoint patch. Never overwrite or delete a prior
   archive.
6. Locate `scripts/package_checkpoint.py` in this skill directory. In an Open
   Design plugin run, the directory is staged under the project-local
   `.od-skills/` tree; if its path is not supplied in the prompt, locate the
   single staged `package-design-checkpoint-*/scripts/package_checkpoint.py`
   file there. Do not substitute a manually recreated ZIP. Run:

   ```bash
   python3 /path/to/package-design-checkpoint/scripts/package_checkpoint.py \
     /path/to/project \
     --project-name "Actual OpenDesign Project Name" \
     --namespace "OpenDesign namespace, when present" \
     --primary mockups/comparison.html "Primary comparison canvas" \
     --alternative mockups/mobile-error.html "Mobile validation-error state" \
     --package-metadata /path/outside/project/package-metadata.json \
     --change "Refined comparison hierarchy and added the mobile error state"
   ```

   Repeat `--alternative TARGET LABEL` for every alternative. Use
   `--report-sha256` only when the user needs a final archive digest. Use exact
   `--exclude` paths or intentional globs for project-specific exclusions;
   credential-like files require an exact exclusion. Metadata paths and all CLI
   targets are relative to the source project, before the `project/` archive prefix.
   The old `--index index.md` option is no longer supported.
7. Trust completion only after the helper opens and validates the private ZIP,
   verifies every local root-index target, and publishes atomically. Fix any
   missing target, credential boundary, symlink, nonportable name, namespace
   collision, or existing destination; do not bypass the guardrail.
8. Return the checkpoint archive or clickable link with its exact filename,
   version, primary target, alternative labels, and intentional exclusions.
   Include the SHA-256 only when it was requested. Explicitly call the package a
   nonfinal checkpoint and tell the recipient to open root `index.html` first.

## Checkpoint contract

- Name archives `<project-slug>-checkpoint-<MAJOR.MINOR.PATCH>.zip` using the
  explicit project name. Keep namespace metadata separate.
- Preserve all authored paths and bytes together under `project/`. This keeps an
  existing source `index.html`, README, and their relative links intact. Version
  0.2.0 of the skill replaces the previous archive-root overlay layout.
- Preserve prior archives on disk and exclude recognized checkpoint archives
  plus the current project's handoff archives from the new payload so packages
  never recursively nest.
- Exclude VCS data, dependency trees, disposable caches, OS metadata, and the
  `.opendesign-checkpointignore` control file.
- Fail closed on credential-like files unless their exact project-relative path
  is excluded. Do not follow symlinks.
- Generate root `index.html`, `README.md`, and `artifact-manifest.json`, plus
  `_package/verification.json` and `_checkpoint/CHANGELOG.md`, without modifying
  the source directory. The guide presents identity, start here, changes, review
  steps, decisions/blockers, package map, verification, and documentation in order.
- Derive the guide and README from the same navigation metadata; start the README
  with **Open `index.html` first.**. Render empty decisions/blockers explicitly as
  None. Keep the guide self-contained, relative-linked, and usable without scripts.
- Do not generate `_handoff/` metadata, an implementation specification,
  exhaustive component inventory, per-file checksum inventory, fabricated CI/CD
  evidence, or a full implementation handoff. The navigation manifest describes
  the package; it is not the exhaustive handoff manifest. Distinguish passed
  packaging checks from caller-reported project verification and unrun tests.
- Validate sorted portable entry names, source bytes, ZIP CRC, declared targets,
  all local root-index links, and generated metadata before reporting success.
