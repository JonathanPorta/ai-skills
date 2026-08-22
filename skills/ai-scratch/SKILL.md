---
name: ai-scratch
description: Use the designated AI scratch directory for PR-review clones, generated artifacts, experiments, and any working output that does not belong to a specific project checkout. Also handles reclaiming disk space from it on request. Use when creating scratch clones or worktrees, writing generated files that have no home in a project repo, or when the operator asks to clean up, free disk space, or prune the scratch folder.
---

# AI Scratch

There is one designated directory for work that is not part of any project
checkout:

```
~/devel/portaj/ai-scratch
```

Treat it as **quasi-ephemeral**: durable enough to hold a review clone across a
multi-hour session, not durable enough to be the only copy of anything. Anything
that must survive belongs in a repository, not here.

## What goes here

- **PR-review clones and worktrees**, one per PR: `ai-scratch/<repo>-<pr>` or
  `ai-scratch/pr-review-<repo>-<pr>`. Never review inside the operator's real
  checkout — that steals their branch and disturbs in-flight work.
- **Generated artifacts** with no project home: reports, drafts, extracted data,
  conversion output, throwaway scripts.
- **Experiments** you need on disk but do not want to commit anywhere.

## What does not

- Anything that is the only copy. If it matters, commit and push it.
- Anything belonging to a project — that goes in the project repo.
- Secrets. This directory is not a credential store.

## Working rules

- **Stay inside it.** Create a subdirectory per task and keep everything for that
  task there. Do not scatter files at the root.
- **Name so the owner is obvious.** `<repo>-<pr>` beats `tmp2`. The cleanup pass
  and the operator both read these names.
- **Do not delete anything you did not create**, outside a cleanup the operator
  asked for. Another session may be mid-review in a directory that looks idle.
- **`.prrq` is off limits.** The review queue, its event log, and its lock live
  there. Deleting it destroys live claims and verdict history.

## Cleaning up

Run when the operator asks to free disk space, prune scratch, or clean up.

```bash
scripts/scratch-sweep.sh                  # dry run: what is reclaimable and why
scripts/scratch-sweep.sh --dry-run        # identical; reporting is the default
scripts/scratch-sweep.sh --older-than 14  # be stricter about what counts as idle
scripts/scratch-sweep.sh --apply          # delete the reclaimable set
```

**The sequence is fixed, and the confirmation is not optional:**

1. Run it with **no flags** — that is the dry run. It prints available disk
   space, then classifies every entry as `KEEP` (with the reason) or `FREE`
   (with its size). Nothing is deleted.
2. **Show the operator the proposal** — space now, entries and total to reclaim,
   and what is being kept. Do not summarise away the keep reasons; those are what
   make the proposal reviewable.
3. **Explain why nothing in flight is affected.** An entry is only reclaimable
   when *all* of these hold, and saying so plainly is the point:
   - it is not `.prrq`, so no queue state, claim, or audit history is touched;
   - it has not been modified inside the idle window, so nothing an active
     session is working in qualifies;
   - it is not a git repo with uncommitted changes or unpushed commits, so no
     work that exists only here can be lost.
4. **Wait for an explicit yes.** Never run `--apply` in the same turn as the
   proposal, and never infer approval from an earlier instruction.
5. Run `--apply`, then report reclaimed space from the after reading.

If the operator wants something kept that the report marked `FREE`, raise the
idle threshold rather than hand-editing the list — a bigger `--older-than` is
reviewable, a bespoke exclusion is not.

## Safety properties worth knowing

The script refuses to run against `/`, `$HOME`, a symlinked root, or a path
shallower than three levels. It only ever considers **direct children** of the
scratch root, re-checks containment immediately before each delete, and never
follows a symlink out. `--apply` is the only path that removes anything; every
other invocation is a report.
