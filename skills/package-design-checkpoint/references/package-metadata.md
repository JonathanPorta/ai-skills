# Package metadata

Pass `--package-metadata /absolute/path/package-metadata.json` to supply review
context. Store this input outside the project, or intentionally exclude it from
the payload. It is a UTF-8 JSON object. Replace example paths with files that
actually exist in the package; excluded or missing targets fail validation.

Use source-relative paths, not URLs, absolute paths, or `project/`-prefixed archive
paths. The helper encodes links and adds the archive prefix. A source index.html
is a valid primary preview and stays unchanged at project/index.html.

```json
{
  "lifecycle": "Proposed",
  "primary": {
    "path": "mockups/comparison.html",
    "label": "Primary comparison canvas",
    "description": "Open the desktop comparison showing the two proposed navigation treatments."
  },
  "review_targets": [
    {
      "path": "mockups/mobile-error.html",
      "label": "Mobile validation-error state",
      "description": "Check error recovery and legibility on a narrow screen.",
      "role": "alternate"
    }
  ],
  "review_checklist": [
    "Compare the navigation treatments in the primary preview.",
    "Check the mobile error message and recovery action."
  ],
  "decisions": ["Choose the navigation treatment to develop next."],
  "blockers": [],
  "withheld": [],
  "package_map": [
    {"path": "mockups", "role": "review-only", "description": "Browsers can open these proposed interface states locally."},
    {"path": "assets", "role": "source", "description": "Local assets required by the previews."}
  ],
  "verification": {"status": "not-run", "summary": "Project tests have not been run for this review package."},
  "deployment": {"posture": "review-only", "description": "No subtree is approved for deployment."}
}
```

## Fields and defaults

| Field | Contract |
|---|---|
| `primary` | One existing file with `path`, `label`, and optional `description`. Required through metadata or CLI. Metadata may enrich the CLI target; conflicting paths fail. |
| `review_targets` | Existing files with `path`, `label`, `description`, and role `alternate`, `evidence`, or `source`. CLI alternatives can supply the simpler form. |
| `review_checklist` | Ordered strings; defaults to inspecting the declared targets. |
| `decisions`, `blockers`, `withheld` | String arrays; empty lists render **None**. Record unresolved choices, missing assets, and intentional omissions truthfully. |
| `lifecycle` | Human-readable state such as Proposed or Accepted. Use Accepted only for accepted work. |
| `package_map` | Source-relative file/directory rows with a description and role `review-only`, `deployable`, `source`, `documentation`, or `evidence`. Unannotated entries receive conservative source labels. |
| `verification` | `status`: `not-run`, `passed`, or `failed`; summary; `evidence` path for passed/failed. Evidence must be included. The guide labels this caller-reported project verification. |
| `deployment` | `posture`: `review-only`, `implementation-ready`, or `deployable`; optional description. Default review-only. Checkpoints require review-only. Deployable handoffs require an actual source-relative directory path, passed project verification with evidence, and no outstanding decisions/blockers/withheld items. |

Unknown fields fail validation. Identity, version, change summary, and creation
date come from the helper invocation and its version calculation, not duplicate
metadata fields. `--change` supplies the checkpoint summary; `--bump-reason`
supplies the handoff summary. Keep them concise.

For an accepted handoff, set lifecycle to Accepted and deployment posture to
implementation-ready. This communicates implementation readiness without saying
the archive root may be deployed. To authorize a specific verified subtree, use
deployable posture and its path (for example `dist`), include actual evidence,
and resolve outstanding review items. The helper performs no deployment.

Use the package map to identify included README, changelog, copy/options notes,
source, and verification material. Documentation/evidence rows provide navigation
to those files; automatic links also include the generated README, navigation
manifest, changelog or handoff metadata, and packaging verification report.

## Output and validation

The generated `artifact-manifest.json` is navigation metadata shared by the HTML
and README; it is not a checksum inventory. The package map represents every
root entry and every top-level authored entry under project/. The original source
README remains at project/README.md; root README starts **Open `index.html` first.**

The guide has eight sections in order: identity, start here, changes, review,
decisions/blockers, package map, verification, documentation. It uses inline CSS,
system fonts, semantic headings, and relative links. No JavaScript is needed.

The packager validates its private ZIP before publishing: portable entry names,
source bytes, ZIP CRC, generated metadata, and declared guide links. Handoff
additionally validates its manifest and checksum inventory. The packaging report
describes these checks; it does not claim to have run project tests. Reported
project pass/fail is supplied by the caller with evidence. Prior archives and
source files are never overwritten by guide generation.
