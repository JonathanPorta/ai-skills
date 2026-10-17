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

## Review round 1

The first review found that publishing `recon` made two of its safety promises
part of this repository's contract, and neither held:

- **F1:** the page cap and path lock were not enforced while requests were made.
  `wget -Q` limits bytes, not pages, and the boundary table let `example.com/menu`
  reach the whole host. `scripts/crawl.py` now fetches pages one request at a
  time and checks the page cap, depth, host and path boundary, robots.txt, and
  every redirect target before each request. The table and preflight now show the
  lock the crawler applies.
- **F2:** `make stop` killed any process on the port, and the hosts cleanup
  deleted every line naming the host. The Makefile and a new `hosts.sh` are now
  tested templates under `assets/templates/`. `make stop` signals only the PID
  `make dev` recorded, after confirming it is still that server; `hosts.sh`
  removes only lines carrying its pack tag.

Moving the Makefile out of `SKILL.md` also fixes the `$$1`/`$$2` rewrite, which was
listed below as a follow-up. In the same round, the `package-design-handoff` icon
was centered (its frame sat 7 px right of center) and the `recon` icon's page was
resized to match that frame.

## Out of scope (follow-up)

- Making `AI_SCRATCH_ROOT` and `~/.ai-scratch/config` the shared scratch
  location that `recon` reads, replacing its `$AI_SCRATCH_DIR` and
  `~/ai-scratch` fallback.

## Evidence

| AC | Proof |
|---|---|
| 1 | `cmp` of the installed and committed `SKILL.md` reports no difference. |
| 2–4 | See the diff. |
| 3 | All four icons rendered side by side for review. |
| 5 | `make check`: 4 skills validated, 126 tests passed, 1 skipped. |
| F1 | `tests/test_recon.py`: `--max-pages 1` requests exactly one page on a four-page site; a `/menu` crawl never requests `/other` or `/menu-old`; out-of-boundary redirects, robots.txt, depth, and off-host links are all refused before the request. |
| F2 | `tests/test_recon.py`: an unrelated listener on the port survives `make stop`; the `make dev` server is stopped; a stale PID file is not trusted; a pre-existing `example.com` hosts line survives `add` and `remove`, and the file keeps its mode. The old `stop` target was confirmed to kill the unrelated listener. |
