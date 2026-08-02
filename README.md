# AI Skills

A curated collection of reusable workflows for AI agents. Each skill lives once,
in a standard Agent Skills directory, while harness-specific metadata stays beside
the skill it describes.

The collection is intentionally boring in the best possible way: clone it,
install the skill you need, and let validation catch packaging mistakes before
an agent does something creative with them.

## Skills

| Skill | Purpose | Open Design | OpenAI ChatGPT / Codex | Other Agent Skills harnesses |
|---|---|---|---|---|
| [`package-design-handoff`](skills/package-design-handoff/) | Create immutable design-handoff ZIPs with lowercase kebab-case names, automatic SemVer increments, manifests, checksums, and validation. | Contract-tested at `517f39a…`; local symlink install | Verified | Format-compatible; not yet verified |

Compatibility labels are intentionally conservative:

- **Contract-tested** means the repository pins and tests the harness discovery,
  metadata, and invocation contract at an exact upstream revision.
- **Verified** means the skill and its executable behavior have been tested with
  the named harness family.
- **Format-compatible** means the directory follows the open Agent Skills layout,
  but this repository has not yet completed an end-to-end harness test.
- **Unsupported** will mean a known incompatibility, not merely a missing test.

Update this table as harness support is actually exercised. Do not duplicate a
skill into one directory per agent.

## Repository layout

```text
ai-skills/
├── skills/
│   └── package-design-handoff/
│       ├── SKILL.md
│       ├── README.md
│       ├── agents/
│       │   └── openai.yaml
│       ├── assets/
│       └── scripts/
├── scripts/                 # Collection validation
├── tests/                   # Repository-level behavioral tests
├── tasks/                   # Project requirements and implementation records
├── Makefile                 # Canonical command surface
└── README.md
```

Every direct child of `skills/` is independently installable. Its directory name
must exactly match the `name` in `SKILL.md`. Its README explains that skill's
behavior, requirements, harness-specific installation, and invocation.

## Install a skill

Clone the repository, review the revision you intend to run, and validate it.
Installation is symlink-first: each harness points at the reviewed local checkout
instead of invoking a mutable package-manager installer.

```bash
git clone git@github.com:JonathanPorta/ai-skills.git
cd ai-skills
make check
```

Using a local checkout keeps private-repository authentication in Git and avoids
putting credentials in an installer command. Prefer symlinking each skill from
that checkout so pulls update every installed harness in place. See the
[`package-design-handoff` installation guide](skills/package-design-handoff/README.md)
for Open Design and Codex commands.

## Current manifest decision

This implementation does not add a collection-level `package.json`-style
manifest. That is an implementation choice under review, not a claim of prior
owner ratification. Today the required metadata already lives at skill scope:

- [`SKILL.md`](https://agentskills.io/specification) is already the required
  per-skill manifest and discovery surface.
- `agents/openai.yaml` carries OpenAI-specific interface metadata without
  changing the portable skill instructions.
- Open Design reads the standard `SKILL.md` directly; the pinned integration
  test verifies that its discovery heuristics select the non-image prototype
  path. Local source-checkout installation does not require an
  `open-design.json` marketplace sidecar.
- Git records collection history and reviewable changes.
- Runtime dependencies belong with the script or ecosystem that needs them.
  The current packaging helper uses only Python's standard library.

The Agent Skills community is discussing a collection-level
[`skills.json` and lockfile proposal](https://github.com/agentskills/agentskills/discussions/210),
but it is not a ratified standard. Add a generated catalog or standard manifest
when the owner accepts one or when distribution, dependency resolution, or a
stable specification makes it useful.

## Add a skill

1. Create `skills/<skill-name>/`; use lowercase letters, digits, and hyphens.
2. Add `SKILL.md` with `name` and `description` frontmatter plus concise,
   imperative instructions.
3. Add a concise skill-local README covering purpose, requirements,
   harness-specific installation, and invocation.
4. Add only resources the skill needs: `scripts/`, `references/`, `assets/`, or
   harness metadata under `agents/`.
5. Add or update repository-level behavioral tests when the skill includes
   executable logic.
6. Update the catalog and compatibility table above.
7. Run `make check` before opening a pull request.

## Validation

```bash
make help
make test
make check
```

`make test` runs behavioral and security regressions. `make check` also parses
and validates Agent Skills and OpenAI YAML schemas, naming and field limits,
asset paths, every text or executable resource, hidden Unicode, Python syntax,
and skill-local documentation. It requires GNU Make and Python 3.10 or newer,
with no third-party Python packages.

## Security

Skills can direct an agent to execute bundled code. Review `SKILL.md` and every
script before installing a skill from an untrusted branch or fork. Validation
proves structure and tested behavior; it does not turn source review into an
optional hobby.
