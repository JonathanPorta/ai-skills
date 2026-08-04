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
| [`package-design-handoff`](skills/package-design-handoff/) | Create immutable design-handoff ZIPs with lowercase kebab-case names, automatic SemVer increments, manifests, checksums, and validation. | GitHub plugin import verified; source-checkout contract-tested at `517f39a…` | Verified | Format-compatible; not yet verified |

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

Open Design can import an individual skill directory directly from GitHub. Open
**Plugins**, select **Import plugin** and **From GitHub**, then enter:

```text
github:JonathanPorta/ai-skills@main/skills/package-design-handoff
```

This is an install-time snapshot, not a live checkout. Re-import the same source
or use Open Design's plugin-upgrade command to fetch later changes from `main`.
See the [`package-design-handoff` installation guide](skills/package-design-handoff/README.md)
for screenshots, update behavior, reproducible revision pinning, and the separate
execution-agent installation requirement.

For filesystem-discovered harnesses, clone the repository, review the revision
you intend to run, and validate it. Symlinking those harnesses to the checkout
lets a reviewed pull update their installed copy in place.

```bash
git clone git@github.com:JonathanPorta/ai-skills.git
cd ai-skills
make check
```

Using a local checkout keeps private-repository authentication in Git and avoids
putting credentials in an installer command. Prefer symlinking each skill from
that checkout when the target harness supports filesystem discovery.

## Current manifest decision

This implementation does not add a collection-level `package.json`-style
manifest. That is an implementation choice under review, not a claim of prior
owner ratification. Today the required metadata already lives at skill scope:

- [`SKILL.md`](https://agentskills.io/specification) is already the required
  per-skill manifest and discovery surface.
- `agents/openai.yaml` carries OpenAI-specific interface metadata without
  changing the portable skill instructions.
- Open Design can adapt a standard `SKILL.md` directory into a minimal plugin;
  the GitHub-subpath import has been exercised in the desktop UI. The pinned
  source-checkout integration separately verifies discovery, staging, and
  execution at revision `517f39a…`.
- The skill currently has no `open-design.json` sidecar. It therefore appears as
  a minimal `v0.0.0` plugin, and the selected local execution agent must discover
  its own installation of the skill to load the complete instructions and
  bundled helper. Add a sidecar only when Open Design-native metadata and direct
  plugin-local skill staging are intentionally adopted and tested.
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
