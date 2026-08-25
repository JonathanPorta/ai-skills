# AI Scratch

Gives agents one designated directory for work that does not belong to a project
checkout — PR-review clones, generated artifacts, experiments — and a guarded way
to reclaim the disk it accumulates.

## Why

Review clones and generated output pile up fast. Left unmanaged the scratch
directory grows without bound; deleted carelessly it takes live queue state or
unpushed commits with it. This skill makes the location explicit and the cleanup
boring.

## Contents

- `SKILL.md` — where scratch lives, what belongs there, and the cleanup protocol.
- `scripts/lib-scratch.sh` — the one definition of root identity and root safety,
  shared so the two scripts cannot disagree.
- `scripts/scratch-setup.sh` — show or set the scratch root; recommends one and
  asks before writing anything.
- `scripts/scratch-sweep.sh` — reports reclaimable entries; deletes only with
  `--apply`.

## Configuration

Resolution order, highest first:

1. `--root`
2. `$AI_SCRATCH_ROOT`
3. `~/.ai-scratch/config` (`AI_SCRATCH_ROOT`, `AI_SCRATCH_IDLE_DAYS`)
4. `/tmp/ai-scratch`

The built-in default is a subdirectory of `/tmp`, never `/tmp` itself — sweeping
a shared temp directory would reach files this tool did not create. `--set`
refuses `/`, `$HOME`, `/tmp`, `/var/tmp`, and anything shallower than two levels.

## Cleanup in one line

```bash
scripts/scratch-sweep.sh                          # dry run — propose only
scripts/scratch-sweep.sh --apply --manifest FILE  # after the operator confirms
```

Reporting is the default, so there is no way to delete by forgetting a flag. The
dry run emits a manifest binding the root's identity and every approved
candidate; `--apply` refuses if that manifest was edited, if the root differs, or
if the reclaimable set drifted, and revalidates each object immediately before
removing it.

An entry is reclaimable only when it is not hidden, nothing inside it has changed
within the idle window, and no repository within it — including linked worktrees
and nested repos — holds uncommitted changes or commits missing from every
remote. Anything git cannot be read for is kept. Everything else is kept with the
reason printed.

Set `AI_SCRATCH_ROOT` or pass `--root` to point at a different directory.
