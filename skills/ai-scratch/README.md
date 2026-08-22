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
scripts/scratch-sweep.sh            # dry run (the default) — propose only
scripts/scratch-sweep.sh --apply    # after the operator confirms
```

Reporting is the default, so there is no way to delete by forgetting a flag.
`--dry-run` / `-n` are accepted for readability and change nothing.

An entry is reclaimable only when it is not `.prrq`, has not been modified inside
the idle window (7 days by default), and is not a git repo holding uncommitted
changes or unpushed commits. Everything else is kept, with the reason printed.

Set `AI_SCRATCH_ROOT` or pass `--root` to point at a different directory.
