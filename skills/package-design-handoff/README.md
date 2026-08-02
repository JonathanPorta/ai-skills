# Package Design Handoff

`package-design-handoff` turns a completed Open Design or other design project
into an immutable, versioned delivery ZIP. It exists to make the final handoff
automatic instead of relying on someone to remember the archive convention at
the end of every project.

The skill:

- names archives `<lowercase-kebab-project>-<MAJOR.MINOR.PATCH>.zip`;
- starts at `0.1.0` and chooses an appropriate patch, minor, or major increment;
- recognizes older `-vX.Y.Z.zip` archives while emitting the canonical format;
- packages editable sources, exports, prototypes, assets, code, and handoff notes;
- excludes version-control internals, dependency trees, caches, temporary files,
  and previous handoff ZIPs;
- adds a manifest, checksums, and handoff notes under `_handoff/`; and
- validates the archive and refuses to overwrite an existing version.

The helper requires Python 3.10 or newer and has no third-party dependencies.

## Get the repository

Clone the repository to a stable location. The symlinks below keep each harness
on the checked-out source, so `git pull` updates the installed skill without a
copy step.

```bash
git clone git@github.com:JonathanPorta/ai-skills.git "$HOME/src/ai-skills"
cd "$HOME/src/ai-skills"
make check
export AI_SKILLS_REPO="$PWD"
```

Use an absolute checkout path for `AI_SKILLS_REPO` if the repository already
exists elsewhere.

## Install in Open Design

Open Design natively loads `SKILL.md` folders and follows folders symlinked into
an Open Design source checkout's `skills/` directory. Link this repository's
canonical folder instead of copying it:

```bash
export OPEN_DESIGN_REPO="/absolute/path/to/open-design"
ln -s "$AI_SKILLS_REPO/skills/package-design-handoff" \
  "$OPEN_DESIGN_REPO/skills/package-design-handoff"
```

The shared `SKILL.md` intentionally uses only the portable Agent Skills
frontmatter accepted by Codex. Open Design loads that format without
modification. Ask Open Design to "package this project for handoff" or select
`package-design-handoff` from its skills UI.

Restart the Open Design daemon after adding the symlink. Do not run the command
if the destination already contains a real directory you need to keep.

Open Design releases that provide the skill-management CLI can create and index
the local symlink for you:

```bash
od skill add "$AI_SKILLS_REPO/skills/package-design-handoff"
od skill list
```

Confirm that `od` resolves to the Open Design CLI before using that shortcut;
many Unix systems already ship an unrelated octal-dump command named `od`.

No `open-design.json` or Open Design-specific `SKILL.md` fields are required to
install or run this skill. That sidecar is only needed if the skill is later
published as an enriched Open Design marketplace listing.

## Install in Codex

Codex discovers user-wide skills in `$HOME/.agents/skills` and follows symlinked
skill directories:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$AI_SKILLS_REPO/skills/package-design-handoff" \
  "$HOME/.agents/skills/package-design-handoff"
```

For one repository only, link it under that repository's `.agents/skills/`
directory instead:

```bash
mkdir -p .agents/skills
ln -s "$AI_SKILLS_REPO/skills/package-design-handoff" \
  .agents/skills/package-design-handoff
```

Codex normally detects the new skill automatically; restart Codex if it does not
appear. Invoke it explicitly as `$package-design-handoff`, or ask Codex to
package, archive, export, or hand off a completed design project.

## Run the helper directly

The skill normally runs the bundled helper through the active agent. It can also
be called directly:

```bash
python3 "$AI_SKILLS_REPO/skills/package-design-handoff/scripts/package_handoff.py" \
  /absolute/path/to/project \
  --project-name "Human Project Name" \
  --bump patch \
  --bump-reason "Corrected responsive states and completed icon exports"
```

Run the helper with `--help` for explicit-version, output-directory, and custom
exclusion options.
