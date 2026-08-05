# AI Skills

A curated collection of reusable, independently installable Agent Skills. Each
skill lives once under `skills/`; harness-specific metadata and Open Design's
additive plugin sidecar stay beside the portable `SKILL.md` they describe.

## Skills

| Skill | Use it for | Open Design | OpenAI ChatGPT / Codex | Other Agent Skills harnesses |
|---|---|---|---|---|
| [`package-design-checkpoint`](skills/package-design-checkpoint/) | Freeze an interim design state for review, comparison, or later resumption with a root index and concise changelog. | First-class GitHub plugin; current runtime contract-tested at `fe1231e…` | Format-compatible; helper tested, direct harness not yet verified | Format-compatible; not yet verified |
| [`package-design-handoff`](skills/package-design-handoff/) | Deliver an accepted, complete, implementation-ready design package with manifest, checksums, and provenance. | First-class GitHub plugin; current runtime contract-tested at `fe1231e…` | Verified | Format-compatible; not yet verified |

Compatibility labels are conservative:

- **Contract-tested** means the repository pins and exercises the harness's
  production discovery/loading and staging contract at an exact revision.
- **Verified** means the portable skill and executable behavior have been tested
  with the named harness family.
- **Format-compatible** means the directory follows the Agent Skills layout but
  has not completed an end-to-end harness test here.

## Checkpoint or handoff?

| Concern | Checkpoint (`/checkpoint` shorthand) | Handoff (`/handoff` shorthand) |
|---|---|---|
| Lifecycle point | In progress: review, compare, preserve, or resume | Accepted: complete and implementation-ready |
| Archive filename | `<slug>-checkpoint-X.Y.Z.zip` | `<slug>-X.Y.Z.zip` |
| Version stream | Independent; patch by default | Independent; scope-sensitive patch/minor/major |
| Payload emphasis | Current mockups, prototypes, states, alternatives, nonvisual design artifacts, required local assets | Complete shippable sources, exports, specs, implementation notes, and provenance |
| Navigation | Required root `index.html` or `index.md`; one primary plus functionally labeled alternatives | No checkpoint-style launcher inventory required |
| Generated metadata | Concise `_checkpoint/CHANGELOG.md` only | `_handoff/README.md`, manifest, and per-file checksums |
| Final ZIP SHA-256 | Optional | Required |
| Claim | Explicitly nonfinal | Complete final delivery |

The slash forms in this table are human shorthand, not Open Design slash
commands. In Open Design, install and apply the corresponding plugin from the
Plugins UI.

## Repository layout

```text
ai-skills/
├── skills/
│   ├── package-design-checkpoint/
│   │   ├── SKILL.md
│   │   ├── README.md
│   │   ├── open-design.json
│   │   ├── agents/openai.yaml
│   │   ├── assets/
│   │   └── scripts/
│   └── package-design-handoff/
│       └── ...same portable plugin shape...
├── scripts/                 # Collection validation
├── tests/                   # Behavioral, security, and integration tests
├── tasks/                   # Requirements and implementation records
├── Makefile                 # Canonical command surface
└── README.md
```

Every direct child of `skills/` is independently importable. Its directory name
must match both `SKILL.md` and `open-design.json` identity.

## Install in Open Design

Open **Plugins → Import plugin → From GitHub** and import the individual plugin
you need:

```text
github:JonathanPorta/ai-skills@main/skills/package-design-checkpoint
github:JonathanPorta/ai-skills@main/skills/package-design-handoff
```

This GitHub-subdirectory import installs an Open Design **plugin**. It is
expected to appear under **Plugins**, not as a separately installed item in Open
Design's **Skills** list. There is no second Open Design Skills-install step.

Apply it from the project's **+ → Plugins** picker, the installed card's **Use**
menu, or by selecting the installed result from the `@` picker's **Plugins**
section. Typing the literal text `/checkpoint`, `/handoff`,
`$package-design-…`, or a plugin name without selecting the installed plugin is
not equivalent to applying it. The slash forms are conversational shorthand,
not native Open Design commands.

Each `open-design.json` declares its local `SKILL.md` under
`od.context.skills`. Current Open Design injects that body and stages the entire
plugin directory—including its Python helper—into the active project. A second
installation in the selected local execution agent is therefore not required
for a run launched through the applied Open Design plugin. Do not assume that a
delegated child thread received the active plugin binding: keep final packaging
in the applied parent run, or explicitly pass the staged `SKILL.md`/helper path
and instructions. A separately launched session outside that run needs its own
normal skill installation.

GitHub imports are install-time local copies. Open Design does not poll `main`;
repeat the same import to fetch updates. Re-import replaces the installed plugin
files, so new runs use the refreshed copy. Open Design preserves applied
manifest/query metadata, but the tested runtime does not content-address
historical plugin-local `SKILL.md` or helper bytes. Replace `main` with a reviewed
commit SHA and leave that installation unchanged when byte-for-byte replay
matters.

The packaged macOS app does not put Open Design's source-checkout CLI on
`PATH`. `/usr/bin/od` is an unrelated octal/hex dump utility, so do not use it
for desktop plugin updates. The handoff guide includes the observed command
output and the supported re-import flow.

## Install for direct agent use

Clone and validate a reviewed revision:

```bash
git clone git@github.com:JonathanPorta/ai-skills.git "$HOME/src/ai-skills"
cd "$HOME/src/ai-skills"
make check
export AI_SKILLS_REPO="$PWD"
```

For Codex user-wide discovery, link whichever portable skills you want:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$AI_SKILLS_REPO/skills/package-design-checkpoint" \
  "$HOME/.agents/skills/package-design-checkpoint"
ln -s "$AI_SKILLS_REPO/skills/package-design-handoff" \
  "$HOME/.agents/skills/package-design-handoff"
```

Symlinking keeps the installed agent on the reviewed checkout. Review and run
`make check` before advancing that checkout. Other Agent Skills-compatible
harnesses use their own configured skill directory.

## Manifest policy

The repository intentionally has no collection-level package manifest. Each
independent plugin already carries the metadata its consumers need:

- `SKILL.md` is the portable Agent Skills contract and direct-agent discovery
  surface.
- `agents/openai.yaml` supplies OpenAI-specific interface metadata without
  changing portable behavior.
- `open-design.json` is an additive Open Design sidecar. `compat.agentSkills`
  advertises portability, while `od.context.skills[{"path":"./SKILL.md"}]`
  activates the plugin-local workflow and companion-file staging.
- Git records collection history and reviewable changes.
- Both helpers use only Python's standard library.

Add a generated catalog or standard collection manifest when a stable
distribution or dependency-resolution contract makes it useful.

## Add a skill

1. Create `skills/<skill-name>/` with a lowercase kebab-case name.
2. Add concise imperative `SKILL.md` instructions with matching `name` and a
   precise trigger description.
3. Add a README covering purpose, requirements, installation, invocation,
   updates, and relevant product boundaries.
4. Add `open-design.json` with matching identity/stable SemVer, portable
   compatibility metadata, and an explicit plugin-local skill binding.
5. Add only required `scripts/`, `references/`, `assets/`, and `agents/`
   resources; keep an imported skill subtree self-contained.
6. Add behavioral tests for executable logic and update this catalog.
7. Run `make check` before publication.

## Validation

```bash
make help
make test
make check
```

`make test` runs behavioral and security regressions. `make check` also validates
Agent Skills and OpenAI YAML, Open Design sidecar identity and local paths,
resource references, hidden Unicode, JSON, Python syntax, naming, and
skill-local documentation. It requires GNU Make and Python 3.10 or newer, with
no third-party Python packages.

The current Open Design contract test is separate because it checks out and
installs the exact pinned upstream runtime:

```bash
make integration-open-design OPEN_DESIGN_REPO=/path/to/pinned/open-design
```

## Security

Skills can direct an agent to execute bundled code. Review `SKILL.md`,
`open-design.json`, and every script before installing an untrusted revision.
Validation proves structure and tested behavior; it does not replace source
review.
