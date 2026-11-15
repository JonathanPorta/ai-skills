# Tasks: Portable project workflow

Requirements and validation: [PRD](prd-project-workflow.md).

- [x] 1. Make tracker paths and companion inputs configurable; retain existing rendering and ownership checks (AC 1, 7).
- [x] 2. Add numbered assignment lifecycle, generated index, evidence checks, and generic templates (AC 2–5, 7).
- [x] 3. Define measurable evaluation and exercise an independent generic handoff (AC 6, 7).
- [x] 4. Validate the integrated diff and prepare reviewable PRs (all ACs).

## Preflight

Validation plan saved: yes, in the PRD. Relevant files read: yes, see codebase
analysis. Canonical commands identified: `make check` and `make test`.
Criteria mapped above. Validation review mode: auto-proceed within the operator's
approved implementation and PR request. Source publication is authorized;
acceptance and merge remain separate.

## Validation results

Implementation is ready for PR review. `make check` validated seven skills and
ran 348 tests: 347 passed, one optional external-runtime integration test skipped.
Tracker regressions: 38 passed. Workflow regressions: 29 passed. Thirteen local
skill-document links and ten notes-adapter links resolved; JSON and whitespace
checks passed. A fresh independent reviewer rejected a structurally valid,
incomplete fictional handoff and preserved two owned gaps.

See [validation evidence](validation-project-workflow.md). These checks establish
helper behavior and one synthetic handoff, not installation or improved real-world
outcomes. Acceptance and merge remain outstanding.
