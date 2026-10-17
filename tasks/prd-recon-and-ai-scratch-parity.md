# PRD: Add Recon and Bring AI Scratch Level With the Design Skills

## Summary

`recon` existed only as a loose `SKILL.md` in one machine's Claude Code skill
directory, with no history or backup. `ai-scratch` was in this repository but
lacked the icon, OpenAI metadata, install documentation, and catalog entry that
the two `package-design-*` skills have. This change is packaging only: it adds
`recon` to the collection and fills `ai-scratch`'s gaps without changing either
skill's behavior.

## Acceptance Criteria

1. `skills/recon/` contains the existing `SKILL.md` byte-for-byte, plus
   `README.md`, `open-design.json`, `agents/openai.yaml`, and `assets/icon.svg`.
2. `skills/ai-scratch/` gains `assets/icon.svg`, `agents/openai.yaml`, an
   `icon` entry in `open-design.json`, and README sections for installation
   and direct use.
3. Both new icons use the same 128×128 tile, navy background, and mint, amber
   and coral palette as the existing icons.
4. The root README lists both skills in the catalog table, the layout tree, the
   Open Design import list, and the direct-install commands, with conservative
   compatibility labels.
5. `make check` passes.

## Out of scope (follow-up)

- Making `AI_SCRATCH_ROOT` and `~/.ai-scratch/config` the shared scratch
  location that `recon` reads, replacing its `$AI_SCRATCH_DIR` and
  `~/ai-scratch` fallback.
- Fixing the `recon` Makefile template's `$$1`/`$$2`, which the skill loader
  rewrites when `/recon` is invoked with arguments.

## Evidence

| AC | Proof |
|---|---|
| 1 | `cmp` of the installed and committed `SKILL.md` reports no difference. |
| 2–4 | See the diff. |
| 3 | All four icons rendered side by side for review. |
| 5 | `make check`: 4 skills validated, 112 tests passed, 1 skipped. |
