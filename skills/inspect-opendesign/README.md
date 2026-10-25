# Inspect OpenDesign

Let a local Codex, Claude Code, or other Agent Skills agent inspect OpenDesign
from outside its harness. List projects and runs, filter artifacts by extension,
find separately versioned handoffs/checkpoints, and copy existing files.

## Requirements and installation

Use Python 3.10+ and a running OpenDesign desktop instance on the agent's machine.
The desktop session must be signed in for workspace-backed projects. No Python
dependencies, API key, or OpenDesign plugin installation are required.

From a reviewed ai-skills checkout:

```bash
make check
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/skills/inspect-opendesign" "$HOME/.agents/skills/inspect-opendesign"
```

For Claude Code, link the same directory under `~/.claude/skills/` instead.
Do not overwrite an existing installation blindly. Update the checkout to a
reviewed revision and rerun `make check`; the symlink follows that checkout.

## Invocation

Example: “Use inspect-opendesign to check my branding project's run status and
get its latest checkpoint ZIP.” Another: “List the handoff ZIPs in OpenDesign,
sorted by version.”

The [skill](SKILL.md) describes listener and workspace discovery. Once configured:

```bash
export OD_INSPECT="$PWD/skills/inspect-opendesign/scripts/opendesign.py"
export OD_URL='http://127.0.0.1:PORT'  # Use the actual observed API port.
python3 "$OD_INSPECT" health
python3 "$OD_INSPECT" workspaces
export OD_WORKSPACE_ID='workspaceId-from-directory'
export OD_MEMBER_ID='workspaceMemberId-from-same-entry'
python3 "$OD_INSPECT" projects
python3 "$OD_INSPECT" runs 'PROJECT_ID'
python3 "$OD_INSPECT" files 'PROJECT_ID' --ext .zip
python3 "$OD_INSPECT" download 'PROJECT_ID' 'project-checkpoint-0.1.0.zip' \
  --output '/absolute/existing-directory/project-checkpoint-0.1.0.zip'
```

Global flags `--url`, `--workspace-id`, `--member-id`, and `--timeout` precede the
subcommand. JSON is printed to stdout; errors go to stderr with a nonzero status.
`files --kind handoff` and `files --kind checkpoint` select filename candidates;
`--kind archive` selects unclassified ZIPs. `--sort mtime` selects newest modified.

## Product boundaries

- This is an external-agent inspection skill, not a generation endpoint or
  packaging replacement. It retrieves outputs from `package-design-handoff`
  and `package-design-checkpoint` without rebuilding or renaming them.
- The helper sends GET requests only to loopback HTTP, refuses redirects,
  and never overwrites downloads or extracts ZIPs. It does not mutate project
  content, cancel runs, or switch active workspaces.
- OpenDesign's own GET workspace listing may bind legacy projects internally.
- Filename matches are candidates. ZIP metadata markers refine classification
  but are not proof of completeness or payload checksum validity.
- For project slugs ending in `-checkpoint`, inspect all ZIPs: a handoff filename
  is ambiguous with a checkpoint filename until its metadata is read.
- Desktop ports can change. A cloud sandbox's localhost is a different machine.
- The additive `open-design.json` follows collection conventions; this workflow
  does not require importing it into OpenDesign.

API behavior is source-checked against OpenDesign 0.25.0 and covered by local HTTP
fixtures. Live desktop end-to-end execution has not been verified here. See the
[API reference](references/api.md) for known inventory omissions and source links.
