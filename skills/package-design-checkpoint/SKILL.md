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
4. Choose the root index:
   - Use `index.html` when two or more declared targets are browsable HTML
     mockups.
   - Use `index.md` when an HTML launcher does not make sense.
   - If the selected root index already exists, it must link every declared
     target, contain the functional labels, and have no broken or unsafe local
     links. Otherwise the helper generates it inside the ZIP without modifying
     the project directory.
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
     --index index.html \
     --primary mockups/comparison.html "Primary comparison canvas" \
     --alternative mockups/mobile-error.html "Mobile validation-error state" \
     --change "Refined comparison hierarchy and added the mobile error state"
   ```

   Repeat `--alternative TARGET LABEL` for every alternative. Use
   `--report-sha256` only when the user needs a final archive digest. Use exact
   `--exclude` paths or intentional globs for project-specific exclusions;
   credential-like files require an exact exclusion.
7. Trust completion only after the helper opens and validates the private ZIP,
   verifies every local root-index target, and publishes atomically. Fix any
   missing target, credential boundary, symlink, nonportable name, namespace
   collision, or existing destination; do not bypass the guardrail.
8. Return the checkpoint archive or clickable link with its exact filename,
   version, primary target, alternative labels, and intentional exclusions.
   Include the SHA-256 only when it was requested. Explicitly call the package a
   nonfinal checkpoint.

## Checkpoint contract

- Name archives `<project-slug>-checkpoint-<MAJOR.MINOR.PATCH>.zip` using the
  explicit project name. Keep namespace metadata separate.
- Package project-root contents directly, without an outer wrapper directory.
- Preserve prior archives on disk and exclude recognized checkpoint archives
  plus the current project's handoff archives from the new payload so packages
  never recursively nest.
- Exclude VCS data, dependency trees, disposable caches, OS metadata, and the
  `.opendesign-checkpointignore` control file.
- Fail closed on credential-like files unless their exact project-relative path
  is excluded. Do not follow symlinks.
- Add only the selected root index (when generation is needed) and
  `_checkpoint/CHANGELOG.md` without modifying the source directory.
- Do not generate `_handoff/` metadata, an implementation specification,
  exhaustive component inventory, internal file manifest, internal checksum
  inventory, CI/CD evidence, or a full implementation handoff.
- Validate sorted portable entry names, source bytes, ZIP CRC, declared targets,
  all local root-index links, and generated metadata before reporting success.
