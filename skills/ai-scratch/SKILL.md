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
     in a directory, or an editor with a file open, keeps that entry;
   - its owner has said so: exactly one well-formed ownership record names it
     and says `"complete": true` and `"released": true`. An entry with no
     record is kept, however clean, pushed and idle it is.
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

If the operator wants something kept that the report marked `FREE`, set
`"released": false` in its ownership record (or pin it with `--protect`) rather
than hand-editing the list — a record and a pin are reviewable, a bespoke
exclusion is not.

## Hold, lenders, and the source layout

- **Hold.** `scripts/scratch-setup.sh --hold "reason"` records `AI_SCRATCH_HOLD` in the config. While it
  stands, every dry run prints `HOLD ACTIVE` and every `--apply` refuses (exit 3) before it reads a
  manifest, in every session that shares the config. Name pins (`--protect`) only cover entries that
  existed when they were written; a hold covers entries created afterwards. `--release` lifts it. Use a
  hold whenever a recovery, migration or audit is in progress.
- **Dependencies are never reclaimable.** Before classifying, the sweep builds a dependency index:
  every `objects/info/alternates` target (relative paths resolved against the borrower's objects
  directory, symlinks resolved, chains followed because every repository's own alternates file is read),
  the primary of every linked worktree it finds (the `gitdir:` pointer), and anything named by
  `GIT_ALTERNATE_OBJECT_DIRECTORIES`. An entry that appears in the index is kept however clean, pushed and
  idle it is, and so is an entry whose `.git/worktrees` points outside itself. **Coverage:** the root at
  full depth, the root's parent to depth 5 (enough to see a sibling clone's alternates file), and every
  directory in `AI_SCRATCH_LENDER_SCAN`; a dependency declared anywhere else is not seen, so name that place
  in `AI_SCRATCH_LENDER_SCAN`. A dependent that lives inside the entry itself (a submodule, a worktree hosted
  within the entry) does not pin it. If the scan fails, or any directory or alternates file in those
  locations cannot be read, every entry is kept and `--apply` refuses: with a shared parent such as
  `/private/tmp`, one unreadable directory is enough, by design. The dry-run manifest
  records a digest of the index; `--apply` rebuilds it and refuses when it differs, so a borrower created
  between review and apply blocks the apply. Do not create new clones that borrow from a disposable
  repository (`git clone --shared`, `--reference` without `--dissociate`): a borrower is only as durable as
  its lender, and a borrower of a blob-less partial clone cannot even pass `fsck`.
- **Ownership records are the final gate.** `AI_SCRATCH_OWNERS` (default `~/devel/worktrees/.owners`)
  holds one flat JSON record per task worktree (`"worktree"`: absolute path, `"complete"`, `"released"`,
  plus owner, purpose, branch, PR and dates for humans; one `"key": value` per line, no nesting). An entry
  is reclaimable **only** when exactly one well-formed record names its physical path and says
  `"complete": true` **and** `"released": true`. **No record keeps the entry.** So does a record that is not
  released, two records for one path (ambiguous), or an unreleased record for something inside the entry.
  A malformed or unreadable record cannot be attributed to an entry, so it keeps every entry and makes
  `--apply` refuse until it is fixed (`scratch-setup.sh` names the file). Age, a clean tree and a pushed
  history say an entry is probably safe; only its owner can say it is done with, and the sweep never
  manufactures a release from idleness or from the absence of a running process. Records are written by
  hand or by a helper that uses this library's writer (raw UTF-8 only; `\uXXXX` escapes are refused, not
  guessed at); `scratch-setup.sh` shows the directory, how many records are released, and any malformed file.
- **Idle is a filter, not an authorization.** The idle window selects what is examined; only the keep
  rules (clean, pushed, no lender, no host, not pinned, not held, complete + released record) decide
  what is reclaimable.
- **Source layout.** Human checkouts stay under `~/devel/portaj/<repo>`. Agent task worktrees go under
  `~/devel/worktrees/portaj/<repo>/<task>` with an ownership record at
  `~/devel/worktrees/.owners/<repo>/<task>.json` (owner, purpose, branch, PR, complete, released);
  cleanup of such a worktree requires the record to say complete and released. No unique work may live
  only under `/private/tmp`: give it a ref in the common dir before the session ends.

## Task worktrees (`wt.sh`)

Agent task worktrees have one lifecycle, and it writes the ownership records the
sweep reads, so a worktree started this way is never reclaimed behind its
owner's back, and once its owner releases it the sweep's remaining rules (idle,
clean, every commit on a remote, no dependency, no hold) decide.

```bash
export WT_OWNER="<session id>"                       # once per session; two sessions must never look alike
scripts/wt.sh start <repo> <task> [--branch B] [--base REF] [--purpose TEXT]
scripts/wt.sh list [<repo>]
scripts/wt.sh finish <repo> <task> [--pr URL] [--note TEXT] [--bundle FILE] [--release] [--no-fetch]
scripts/wt.sh check  <repo> <task> [--for-removal] [--no-fetch]
```

- `start` creates `~/devel/worktrees/portaj/<repo>/<task>` from the canonical
  primary `~/devel/portaj/<repo>` (`git worktree add`, after a fetch) and writes
  `~/devel/worktrees/.owners/<repo>/<task>.json`. It never switches the primary's
  branch, never clones, never borrows objects (a primary with `alternates` is
  refused), and never places work under `/private/tmp`. The same owner resumes
  with the same command; another owner is refused, an existing directory without
  a record is refused, a released task name is refused, and `..`, `/`, spaces or
  control characters in a name are refused.
- `list` shows owner, branch, PR, last activity, state (ACTIVE / COMPLETE /
  RELEASED) and blockers: dirty, unpushed, missing, unregistered, hosts
  worktrees, lends or borrows objects, awaiting cleanup, malformed record.
- `finish` records completion plus the preservation evidence. Required history
  is HEAD plus every commit in the worktree's private reflog; each is preserved
  only when, checked against the **current** state, it is reachable from the
  remote default branch (fetched now), or a local `refs/keep/*` ref reaches it
  **and** the bundle named by `--bundle` contains it (the bundle is restored
  into an empty repository offline on every check; its sha256 is recorded). A
  pushed task branch's live tip is not a basis (the branch can be deleted by a
  later merge), and neither is a merged PR's head ref, a stale remote-tracking
  ref or a note. Preservation does not establish completion or owner release. `--release` sets
  `"released": true` only when nothing is unpreserved and the worktree is
  clean, hosts and lends nothing and has no nested repository; otherwise it
  records completion, names the blockers and prints the exact `update-ref` /
  `bundle create` commands that would preserve the unpublished commits locally
  (nothing is pushed). It then prints the cleanup plan and **deletes nothing**.
- `check <repo> <task> --for-removal` is the validator the plan runs and the
  same gate list `finish --release` uses: record complete (and released),
  repository as git reports it (a record naming another primary fails),
  registered, not locked, clean, hosts and lends nothing, no nested repository,
  every required commit preserved. The plan is that one command followed by the
  non-forced `git worktree remove`; removal stays in that flow. `--no-fetch`
  assesses offline, so only keep refs + bundle count; `finish`/`check` otherwise
  fetch origin's default branch into the
  primary's remote-tracking ref, which is the only thing they write besides the
  record. A worktree released on keep refs + bundle is cleaned only through the
  printed plan: the sweep's own "every commit on a remote" rule treats
  `refs/keep/*` as local-only history and keeps every worktree of that primary.

`WT_ROOT`, `WT_PRIMARIES`, `WT_BUNDLES` (default `~/devel/recovery/bundles`) and
`WT_BRANCH_PREFIX` (default `jp/f/`) can be set in the environment or in
`~/.ai-scratch/config` (absolute paths; `~/` expands).
Things to know: with `WT_OWNER` unset the owner is `user@host`, so two sessions
look alike; `--owner` is the owner's statement, not a check, and `--pr` is informational
(a merged PR's head ref is not preservation); `start` fetches from origin, which updates the primary's
remote-tracking refs and nothing else; one malformed record anywhere under the
ownership directory stops every `start` until it is fixed; released records
stay behind as history after the worktree is removed (delete them by hand when
the primary no longer lists the worktree); the plan `finish` prints is the
whole removal procedure, and it is never run for you.

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
