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
  and previous handoff ZIPs from the same project series;
- fails closed on credential-like files unless an exact path is reviewed for
  exclusion or explicit inclusion;
- rejects symlinked controls and non-portable or colliding ZIP entry names;
- adds a manifest, checksums, and handoff notes under `_handoff/`; and
- validates and fsyncs a private archive before atomic no-clobber publication.

The helper requires Python 3.10 or newer and has no third-party dependencies.

## Get the repository

Clone the repository to a stable location and check out a revision you have
reviewed. The symlinks below keep each harness on that exact local source;
review and validate future updates before moving the checkout forward.

```bash
git clone git@github.com:JonathanPorta/ai-skills.git "$HOME/src/ai-skills"
cd "$HOME/src/ai-skills"
make check
export AI_SKILLS_REPO="$PWD"
```

Use an absolute checkout path for `AI_SKILLS_REPO` if the repository already
exists elsewhere.

## Install in Open Design

Open Design's contract at commit
`517f39acde402c1a7af2189167a8d6957a3dac71` loads `SKILL.md` folders from a
source checkout's `skills/` directory. Link this repository's canonical folder
instead of copying it:

```bash
export OPEN_DESIGN_REPO="/absolute/path/to/open-design"
ln -s "$AI_SKILLS_REPO/skills/package-design-handoff" \
  "$OPEN_DESIGN_REPO/skills/package-design-handoff"
```

The shared `SKILL.md` uses strict standard Agent Skills frontmatter. The pinned
integration runs Open Design's production discovery and staging functions,
confirms the utility resolves to the non-image `prototype` path, and invokes the
packager through the staged skill copy. Ask Open Design to "package this project
for handoff" or select `package-design-handoff` from its skills UI.

Restart the Open Design daemon after adding the symlink. Do not run the command
if the destination already contains a real directory you need to keep.

The pinned Open Design CLI can inspect discovered skills but cannot install
them. After restarting the daemon, verify the source-checkout link with:

```bash
od skills list
od skills show package-design-handoff
```

Confirm that `od` resolves to the Open Design CLI before using that shortcut;
many Unix systems already ship an unrelated octal-dump command named `od`.

Do not use the retired singular install command. Re-test newer Open Design
revisions before expanding the compatibility claim. An `open-design.json`
sidecar is not needed for this source-checkout workflow; marketplace/plugin
distribution is a separate contract.

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
exclusion options. Credential-like files require either an exact `--exclude`
path or a deliberately reviewed exact `--include-sensitive` path; globs do not
count as credential review.
