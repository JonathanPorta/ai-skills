# Inspect OpenDesign

## Request and scope

Add a basic portable skill for agents outside OpenDesign to inspect local project
status, inventory artifacts, and retrieve existing handoff/checkpoint ZIPs.
The user's current-session request authorizes this implementation in ai-skills.
Generation, packaging, source edits, deployment, and merging are outside scope.

## Codebase analysis

- `skills/package-design-{handoff,checkpoint}/SKILL.md` define independent stable
  version streams and different archive metadata; filenames alone are candidates.
- `scripts/check_skills.py` requires a skill README and OpenDesign sidecar for
  every skill. Preserve that collection convention without requiring OpenDesign
  plugin installation for this external-agent workflow.
- `Makefile` exposes `make check` (structure plus behavioral tests), `make test`,
  and a separate pinned runtime integration target. No new build/dev target is needed.
- OpenDesign 0.25.0 requires workspace-scoped project listing and a matching
  workspace/member header pair. Project lifecycle is distinct from run status.

## Acceptance criteria

1. A local agent can discover the desktop API port and select an authorized
   workspace without hardcoded user paths, ports, or membership identifiers.
2. GET-only commands expose projects, project details, runs, and files with
   preserved errors and explicit guidance for absent/unknown status fields.
3. ZIP inventory supports extension and package-kind filters and descending
   numeric versions within each project/package series.
4. Download an existing listed artifact with encoded paths, no extraction or
   overwrite, and a SHA-256; distinguish archive metadata from filename guesses.
5. The portable skill, documentation, and tests pass `make check`; compatibility
   claims distinguish source/fixture verification from a live desktop test.

## Validation plan

Before implementation, define loopback HTTP fixtures covering workspace headers,
unbound listing, wrong-server HTML, HTTP error bodies, scoped runs, numeric sorting,
nested path encoding, ZIP metadata, invalid ZIPs, and destination preservation.
Use Python's standard library only. Run the skill validator and `make check`.
The remote authoring environment cannot reach the user's Mac localhost; do not
claim a live end-to-end test.
