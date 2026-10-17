# Recon

`recon` captures a public website as a self-contained research pack. Capture
detail scales from a one-page "what's the vibe?" summary to a snapshot that
replays the site at its original hostname in Docker.

Use it to hand a site to a designer, do competitive research, archive a
snapshot, or stand up a local replay.

## Capture tiers

| Tier | Use case | Output | Size |
|---|---|---|---|
| `gist` | One-page vibe check | `GIST.md` only | < 1 MB |
| `design` *(default)* | Designer hand-off | Brand brief, tech stack, DNS report, page walk, image library | 20–50 MB |
| `pixel-perfect` | Visual archive, viewed online | `design` plus all CSS, JS, and fonts (CDN-linked) | 50–150 MB |
| `offline` | Self-contained snapshot | Every dependency localized, URLs rewritten | 100–300 MB |
| `forensic` | Replay at the original hostname | `offline` plus `serve/` (Dockerfile, nginx config, optional self-signed TLS) | 100–300 MB |

Every tier shows a preflight plan (boundary, page and depth caps, robots.txt
handling, destination) and waits for confirmation before downloading.

## Requirements

- Python 3.10 or newer, `curl`, `dig`, and `whois` on `PATH`. The bundled
  crawler uses only Python's standard library.
- Optional: `playwright` (a homepage screenshot for `gist`) and Docker (to run a
  `forensic` replay).

## Boundaries

Pages are fetched by `scripts/crawl.py`, one request at a time. It checks every
limit before each request, so the crawl cannot exceed the plan you confirmed:

- **Host:** the hostname you gave, exactly. Off-host links are never followed.
- **Path:** a URL with a path (`example.com/menu`) is locked to that path and
  below. Give the site root, or add `--include`, to widen it.
- **Platforms:** on GitHub, X, LinkedIn, Medium, YouTube and similar, the lock is
  the user or project namespace, and a bare platform root is refused unless you
  say otherwise.
- **Caps:** 50 page requests and 3 levels deep by default.
- **Encoded paths:** every link is checked after percent-decoding and resolving
  `.`/`..` segments, so `/menu/%2e%2e/other` cannot leave a `/menu` lock.
- **robots.txt** is respected by default. If it cannot be read (anything other
  than "not found"), the crawl stops before requesting any page unless you pass
  `--ignore-robots`. Redirects that leave the boundary are not followed.

Analytics and tracking scripts are never captured.

Only point it at sites you have a legitimate reason to capture: public marketing
sites and your own properties are fine. It cannot reach login-walled content.

## Install for direct use

Clone and validate a reviewed revision, then link the skill into your agent's
skill directory:

```bash
git clone git@github.com:JonathanPorta/ai-skills.git "$HOME/src/ai-skills"
cd "$HOME/src/ai-skills"
make check
export AI_SKILLS_REPO="$PWD"

# Claude Code
ln -s "$AI_SKILLS_REPO/skills/recon" "$HOME/.claude/skills/recon"
# Codex
ln -s "$AI_SKILLS_REPO/skills/recon" "$HOME/.agents/skills/recon"
```

For Open Design, import the plugin from **Plugins → Import plugin → From
GitHub**:

```text
github:JonathanPorta/ai-skills@main/skills/recon
```

## Use

```text
/recon https://example.com                  # asks which tier you want
/recon https://example.com --mode gist      # no tier prompt
/recon https://example.com --mode offline ~/Desktop/example-snapshot
```

Other flags: `--max-pages N`, `--depth N`, `--include <regex>`,
`--exclude <regex>`, `--ignore-robots`, `--force-platform-root`.

## Where packs are written

Without an explicit destination, packs go to `$AI_SCRATCH_DIR` if it is set,
otherwise to `~/ai-scratch/`, in a folder named `<host>-<YYYY-MM-DD>`. An
existing non-empty folder is never overwritten; `recon` offers alternative names
instead.

## Viewing and replaying a pack

`make dev` serves the capture locally and `make stop` stops that server only; it
never touches anything else listening on the port. A `forensic` pack's
`serve/hosts.sh add` and `remove` manage one tagged `/etc/hosts` line, so your
own mappings for the same hostname are left alone. Recon edits are serialized
with a lock. If another program changes the file while the script prepares its
edit, the script keeps that newer file and asks you to run it again. The one
case it cannot catch is a program that replaces the file by rename in the
instant before the script's own rename; avoid editing `/etc/hosts` by other
means while `hosts.sh` runs.

Scratch directories are meant to be temporary. Copy a pack somewhere permanent
if you intend to keep it.
