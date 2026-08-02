---
name: package-design-handoff
description: Package a completed OpenDesign or other design project into an immutable, complete, versioned handoff ZIP. Use when finishing, exporting, archiving, handing off, revising, or correcting a design project; when the user asks to combine all design assets or deliverables; or when a handoff archive needs a lowercase kebab-case project name and an automatically incremented SemVer suffix.
---

# Package Design Handoff

Create the archive as part of completing the design task. Do not merely remind the user to request one.

## Workflow

1. Identify the final project directory and human-readable project name from the task. Ask only when either is genuinely ambiguous.
2. Finish the requested design work before packaging. Do not change accepted design truth merely to make the archive cleaner.
3. Treat “everything” as every project-authored handoff deliverable: editable sources, exports, prototypes, raster assets, icons, tokens, code, fixtures, fonts or sonic assets that may legally ship, specifications, implementation notes, and relevant provenance. Exclude version-control internals, dependency trees, disposable caches, OS metadata, temporary files, and earlier handoff ZIPs from the same project series. Credential-like files fail closed unless their exact project-relative path is reviewed for exclusion or explicit inclusion. Preserve relative paths from the project root so the ZIP is a root overlay, not a wrapper directory.
4. Select the SemVer increment without asking when the task provides enough evidence:
   - Initial: `0.1.0` when no prior archive exists.
   - Patch: corrections, refinements, regenerated exports, or completion of the same promised scope.
   - Minor: a new screen, direction, asset family, deliverable category, meaningful additive scope, or an incompatible pre-1.0 restructuring.
   - Major: an incompatible restructuring after 1.0 or an explicit major-version request.
5. Write a brief bump reason that says what changed. Never overwrite or mutate a prior archive.
6. Run `scripts/package_handoff.py`, resolved relative to this `SKILL.md`:

   ```bash
   python3 /path/to/package-design-handoff/scripts/package_handoff.py \
     /path/to/project \
     --project-name "Human Project Name" \
     --bump patch \
     --bump-reason "Corrected responsive states and completed icon exports"
   ```

   Use `--output-dir` when archives belong somewhere other than the project root. Use repeatable `--exclude` globs only for intentional project-specific exclusions. Use `--version X.Y.Z` instead of `--bump` only when the user or an accepted handoff explicitly fixes the next version.
7. Trust completion only after the helper validates the private ZIP, publishes it atomically, and prints its SHA-256. If the helper fails because of an unresolved symlink, credential boundary, non-portable name, reserved metadata collision, missing payload, non-monotonic version, or existing destination, fix the cause; do not bypass the guardrail.
8. Return the archive itself or a clickable link, plus its exact filename, version, payload-file count, and SHA-256. Briefly name any intentional exclusions. Do not claim the handoff is complete if the archive is unavailable.

## Archive contract

- Name new archives `<project-slug>-<MAJOR.MINOR.PATCH>.zip`; use lowercase ASCII kebab-case and no `v` prefix.
- Discover both canonical and legacy `-vX.Y.Z.zip` archives when calculating the next version, but emit only the canonical form.
- Package project-root contents directly. Do not add an outer project folder.
- Add `_handoff/README.md`, `_handoff/MANIFEST.json`, and `_handoff/CHECKSUMS.sha256` inside the ZIP without modifying the source directory.
- List every payload file with its size and SHA-256 in the manifest. Record the previous version, bump type, bump reason, and intentional exclusions.
- Sort archive entries and validate their names, bytes, checksums, manifest, and ZIP CRC before reporting success.

Example: if `dont-make-me-think-adaptive-interface-0.2.1.zip` exists, a refinement becomes `dont-make-me-think-adaptive-interface-0.2.2.zip`.
