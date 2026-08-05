# Package Design Checkpoint

`package-design-checkpoint` freezes the current design state for review,
comparison, or later resumption. It preserves mockups, prototypes, alternate
directions, state explorations, nonvisual design material, and required local
assets without claiming that the project is implementation-ready.

This is the interim counterpart to `package-design-handoff`:

- use checkpoint for in-progress review or resumption;
- use handoff for accepted, complete, implementation-ready delivery.

The helper requires Python 3.10 or newer and has no third-party dependencies.

## Open Design plugin source

Import the individual plugin directory from **Plugins → Import plugin → From
GitHub**:

```text
github:JonathanPorta/ai-skills@main/skills/package-design-checkpoint
```

This installs an Open Design **plugin**. It is expected to appear under
**Plugins**, not as a separately installed item in Open Design's **Skills** list,
and there is no second Open Design Skills-install step. Apply **Package Design
Checkpoint** from **+ → Plugins**, the installed card's **Use** menu, or by
selecting the installed result from the `@` picker's **Plugins** section. Typing
the literal text `/checkpoint`, `$package-design-checkpoint`, or the plugin name
without selecting the installed plugin does not attach it. `/checkpoint` is
conversational shorthand, not a native Open Design slash command.

The bundled `open-design.json` binds `./SKILL.md` as plugin-local context. On the
tested Open Design runtime, applying the plugin injects these instructions and
stages this entire directory—including `scripts/package_checkpoint.py`—for the
selected execution agent. A second Codex or Claude skill installation is not
required for a run launched through the applied Open Design plugin. Do not
assume a delegated child thread received the active plugin binding: keep final
packaging in the applied parent run, or explicitly pass the staged
`SKILL.md`/helper path and instructions. A separately launched session outside
that run needs its own normal skill installation.

GitHub imports are install-time local copies. Open Design does not poll `main`;
repeat the same import to refresh the local plugin. Re-import replaces the
installed plugin files, so new runs use the refreshed copy. Open Design
preserves applied manifest/query metadata, but the tested runtime does not
content-address historical plugin-local `SKILL.md` or helper bytes. Pin a
reviewed commit and leave that installation unchanged when byte-for-byte replay
matters.

The packaged macOS app does not add Open Design's source-checkout CLI to
`PATH`. If `which od` prints `/usr/bin/od`, that command is the unrelated Unix
octal/hex dump utility and cannot update Open Design plugins. Use the desktop
re-import flow above.

## Install for direct use outside Open Design

Clone and validate a reviewed revision:

```bash
git clone git@github.com:JonathanPorta/ai-skills.git "$HOME/src/ai-skills"
cd "$HOME/src/ai-skills"
make check
export AI_SKILLS_REPO="$PWD"
```

For Codex, symlink this skill into the user-wide registry:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$AI_SKILLS_REPO/skills/package-design-checkpoint" \
  "$HOME/.agents/skills/package-design-checkpoint"
```

For one repository only, link it under that repository's `.agents/skills/`
directory. Other Agent Skills-compatible harnesses need the corresponding
filesystem installation in their configured registry. Invoke the directly
installed skill as `$package-design-checkpoint` or ask for the in-progress
project to be packaged as a nonfinal review checkpoint.

## Run directly

```bash
python3 "$AI_SKILLS_REPO/skills/package-design-checkpoint/scripts/package_checkpoint.py" \
  /absolute/path/to/project \
  --project-name "Actual OpenDesign Project Name" \
  --namespace "release-stable" \
  --index index.html \
  --primary mockups/comparison.html "Primary comparison canvas" \
  --alternative mockups/mobile-error.html "Mobile validation-error state" \
  --change "Refined hierarchy and added the mobile validation state"
```

The project name is required and is never inferred from the filesystem or a
mockup. The optional namespace is recorded separately. Run `--help` for explicit
version, output-directory, exclusion, dry-run, and SHA-256 options.

## Archive contract

- Filename: `<project-slug>-checkpoint-X.Y.Z.zip`
- Initial version: `0.1.0`; later default: patch
- Root navigation: `index.html` for multiple HTML mockups, otherwise `index.md`
- Generated metadata: `_checkpoint/CHANGELOG.md` only
- Publication: private validation followed by atomic no-clobber publication
- Security: no symlinks; credential-like files require exact exclusion

The helper does not generate a final implementation specification, exhaustive
component inventory, file checksum manifest, CI/CD evidence, or `_handoff/`
metadata.
