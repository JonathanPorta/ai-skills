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

- `curl`, `wget`, `dig`, `whois`, and `python3` on `PATH`.
- Optional: `httrack` (better URL rewriting for `offline`), `playwright` (a
  homepage screenshot for `gist`), and Docker (to run a `forensic` replay).

## Boundaries

`recon` stays on the hostname it was given and never follows off-host links. On
multi-tenant platforms such as GitHub, X, LinkedIn, Medium, or YouTube, it locks
to the user or project namespace in the URL and refuses a bare platform root
unless told otherwise. It respects `robots.txt` by default, caps a crawl at 50
pages and 3 levels deep, and never captures analytics or tracking scripts.

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

Scratch directories are meant to be temporary. Copy a pack somewhere permanent
if you intend to keep it.
