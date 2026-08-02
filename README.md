# AI Skills

A curated collection of reusable workflows for AI agents. Each skill lives once,
in a standard Agent Skills directory, while harness-specific metadata stays beside
the skill it describes.

The collection is intentionally boring in the best possible way: clone it,
install the skill you need, and let validation catch packaging mistakes before
an agent does something creative with them.

## Skills

| Skill | Purpose | OpenAI ChatGPT / Codex | Other Agent Skills harnesses |
|---|---|---|---|
| [`package-design-handoff`](skills/package-design-handoff/) | Create immutable design-handoff ZIPs with lowercase kebab-case names, automatic SemVer increments, manifests, checksums, and validation. | Verified | Format-compatible; not yet verified |

Compatibility labels are intentionally conservative:

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
must exactly match the `name` in `SKILL.md`.

## Install a skill

Clone the repository, validate it, then use the installer supported by your
harness. For installers compatible with the open Agent Skills ecosystem, the
[`skills` CLI](https://github.com/vercel-labs/skills) can install from the local
checkout:

```bash
git clone git@github.com:JonathanPorta/ai-skills.git
cd ai-skills
make check
npx skills add . --skill package-design-handoff
```

Using a local checkout keeps private-repository authentication in Git and avoids
putting credentials in an installer command.

## Why there is no package manifest

There is no custom `package.json`-style configuration file yet because it would
duplicate information and commit this collection to an unsettled convention.

- [`SKILL.md`](https://agentskills.io/specification) is already the required
  per-skill manifest and discovery surface.
- `agents/openai.yaml` carries OpenAI-specific interface metadata without
  changing the portable skill instructions.
- Git records collection history and reviewable changes.
- Runtime dependencies belong with the script or ecosystem that needs them.
  The current packaging helper uses only Python's standard library.

The Agent Skills community is discussing a collection-level
[`skills.json` and lockfile proposal](https://github.com/agentskills/agentskills/discussions/210),
but it is not a ratified standard. Add a generated catalog or standard manifest
when distribution, dependency resolution, or a stable specification makes it
useful—not because an empty config file feels lonely.

## Add a skill

1. Create `skills/<skill-name>/`; use lowercase letters, digits, and hyphens.
2. Add `SKILL.md` with `name` and `description` frontmatter plus concise,
   imperative instructions.
3. Add only resources the skill needs: `scripts/`, `references/`, `assets/`, or
   harness metadata under `agents/`.
4. Add or update repository-level behavioral tests when the skill includes
   executable logic.
5. Update the catalog and compatibility table above.
6. Run `make check` before opening a pull request.

Do not add a README inside an individual skill. Human-facing collection guidance
belongs here; runtime instructions belong in `SKILL.md`.

## Validation

```bash
make help
make check
```

`make check` validates naming, required metadata, UTF-8 and hidden-Unicode safety,
Python syntax, OpenAI interface metadata when present, and repository-level
behavioral tests. It requires GNU Make and Python 3.10 or newer, with no
third-party Python packages.

## Security

Skills can direct an agent to execute bundled code. Review `SKILL.md` and every
script before installing a skill from an untrusted branch or fork. Validation
proves structure and tested behavior; it does not turn source review into an
optional hobby.
