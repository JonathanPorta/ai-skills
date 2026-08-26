---
name: ai-scratch
description: Use the designated AI scratch directory for PR-review clones, generated artifacts, experiments, and any working output that does not belong to a specific project checkout. Also handles reclaiming disk space from it on request. Use when creating scratch clones or worktrees, writing generated files that have no home in a project repo, or when the operator asks to clean up, free disk space, or prune the scratch folder.
---

# AI Scratch

There is one designated directory for work that is not part of any project
checkout. Ask where it is rather than assuming:

```bash
scripts/scratch-setup.sh          # resolved root, and which source set it
```

Resolution order, highest first: `--root` → `$AI_SCRATCH_ROOT` →
`~/.ai-scratch/config` → `/tmp/ai-scratch`. The built-in default is a
*subdirectory* of `/tmp`, never `/tmp` itself — that directory holds files this
tool did not create.

Treat it as **quasi-ephemeral**: durable enough to hold a review clone across a
multi-hour session, not durable enough to be the only copy of anything. Anything
that must survive belongs in a repository, not here.

## First run — configure it, do not guess

If `scratch-setup.sh` reports **NOT CONFIGURED**, it prints a recommendation: an
existing populated scratch directory if it finds one, otherwise the ephemeral
default.

**Present that recommendation and ask.** The operator answers one of three ways:

| Answer | Do |
| --- | --- |
| yes | `scripts/scratch-setup.sh --set <recommended path>` |
| a different path | `scripts/scratch-setup.sh --set <their path>` |
| no | Leave it unconfigured; the built-in default applies. Do not write config. |

Never write the config without an explicit answer — it decides where a
destructive sweep will later point. `--set` refuses `/`, `$HOME`, `/tmp`,
`/var/tmp`, and any path shallower than two levels.

`--idle-days N` sets the default idle window used by the sweep.

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
- **Hidden entries are off limits.** Anything at the root starting with `.` is
  treated as another tool's state — queues, caches, locks, claim files — and is
  never a cleanup candidate. Task output is named `<repo>-<pr>`, so the
  convention separates the two without the skill needing to know any tool by
  name.

## Cleaning up

Run when the operator asks to free disk space, prune scratch, or clean up.

```bash
scripts/scratch-sweep.sh                  # dry run: what is reclaimable, and why
scripts/scratch-sweep.sh --verbose        # list every kept entry, not a summary
scripts/scratch-sweep.sh --older-than 14  # be stricter about what counts as idle
scripts/scratch-sweep.sh --apply --manifest FILE   # delete exactly what was approved
```

**The sequence is fixed, and the confirmation is not optional:**

1. Run it with **no flags** — that is the dry run. It prints available disk
   space, every `FREE` entry with its size, and the kept entries **grouped by
   reason**. Nothing is deleted. Use `--verbose` when the operator wants each
   kept entry listed individually; at a thousand-plus entries the grouped form is
   the readable one.
2. **Show the operator the proposal** — space now, entries and total to reclaim,
   and what is being kept. Do not summarise away the keep reasons; those are what
   make the proposal reviewable.
3. **Explain why nothing in flight is affected.** An entry is only reclaimable
   when *all* of these hold, and saying so plainly is the point:
   - it is not a hidden entry, so no other tool's queue, cache, lock, or claim
     state is touched;
   - nothing anywhere inside it has been modified within the idle window, so a
     session actively editing a file deep in a tree still counts as busy. Git's
     own metadata is excluded: a fetch or an index refresh re-dates `.git`
     without anyone having done work, and a commit that exists only locally is
     caught by the unpushed check below rather than by its timestamp;
   - no repository inside it — including linked worktrees, whose `.git` is a
     file, and repositories nested below the top — has uncommitted changes or
     commits absent from every remote, including on a detached HEAD;
   - git could be interrogated at all. A repository that cannot be read is kept,
     not assumed safe;
   - no process still holds it open. At the moment of deletion the entry has
     already been renamed aside, so nothing can reach it afresh and the only
     processes that could still write to it are those holding a descriptor or
     sitting in it from before — which are enumerated by name. A shell parked
     in a directory, or an editor with a file open, keeps that entry.
4. **Wait for an explicit yes.** Never run `--apply` in the same turn as the
   proposal, and never infer approval from an earlier instruction.
5. Run `--apply --manifest <file>` using the manifest the dry run printed, then
   report reclaimed space from the after reading.

The manifest is what makes the confirmation mean something. It records the root's
identity and every approved candidate by name *and* inode. `--apply` refuses if
the manifest was edited, if the root is not the same directory, or if the
reclaimable set has changed at all since you showed it. Immediately before each
removal it re-checks object identity and re-runs every keep rule, so a directory
replaced or touched after approval is skipped rather than deleted.

If the set has drifted, do not hunt for a workaround: run a fresh dry run and
show the new proposal. The abort means the thing approved is no longer the thing
on disk.

If the operator wants something kept that the report marked `FREE`, raise the
idle threshold rather than hand-editing the list — a bigger `--older-than` is
reviewable, a bespoke exclusion is not.

## Safety properties worth knowing

Both scripts share one definition of a safe root, so setup cannot persist a root
the sweep would refuse. That definition rejects `/`, `$HOME`, shared temp and
system directories, and anything with fewer than two path components — compared
against the canonical physical path, so a symlink cannot smuggle one past.

Roots are stored canonically, never as typed, so a relative path can never be
resolved against whatever directory the sweep happens to run in later.

Candidates are enumerated NUL-delimited and carried through the manifest
hex-encoded, so a filename containing a newline, tab, or glob character cannot
split one record into two or redirect a deletion. Parentage is checked by inode
rather than string prefix. `--apply` is the only path that removes anything.
