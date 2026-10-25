# Local OpenDesign API reference

Verified against upstream tag `open-design-v0.25.0`; recheck response shapes for
other versions. The desktop chooses loopback ports dynamically. The helper accepts
only HTTP origins on `localhost`, `127.0.0.1`, or `::1`, bypasses environment
proxies, and refuses redirects. Remote container access is outside this helper's
current scope; use an explicitly configured local tunnel if needed.

## GET routes

| Purpose | Route | Response |
|---|---|---|
| Health | `/api/health` | `{ok, version, ...}` |
| Workspace directory | `/api/workspace/directory` | `{items, activeWorkspaceId}` |
| Workspace projects | `/api/workspaces/{workspaceId}/projects` | `{projects}` |
| Unbound catalog | `/api/projects` | `{projects}`; workspace headers do not scope it |
| Project details | `/api/projects/{id}` | `{project, resolvedDir}`; omit `ensureDir` |
| Run list | `/api/runs?projectId={id}` | `{runs, awaitingInputProjectIds}` |
| Run details | `/api/runs/{runId}` | Direct run object |
| Recursive files | `/api/projects/{id}/files` | `{files}` |
| Existing file bytes | `/api/projects/{id}/files/{relative-path}` | Binary or text matching the file |

Send `x-od-workspace-id` and `x-od-workspace-member-id` together for workspace-bound
project/run reads. Copy both from the same active membership in the directory.
They declare a context; they are not substitutes for a valid OpenDesign login.
The directory can be read without these headers. Project/run IDs are URL-encoded
segments; file paths encode each segment while preserving separators.

Workspace project rows include `id`, `name`, `workspaceId`, `resourceState`,
`syncState`, timestamps, permissions, and a nested `project` object. They do not
include generation status in this version. Use per-project runs.

File rows include project-relative `name`/`path`, daemon-host `localPath`, `type`,
`size` (bytes), `mtime` (epoch milliseconds), `kind`, `mime`, and optional artifact
metadata. The helper adds filename-based `packageKind`, `projectSlug`, `version`,
and `classification`; these are helper fields, not an OpenDesign API contract.

## Limitations and errors

- File enumeration skips hidden entries, symlinks, `.artifact.json` sidecars,
  and ignored/generated directories such as `dist`, `build`, `out`, dependencies,
  and caches. Confirm `resolvedDir` before a bounded filesystem fallback.
- `/api/runs/{runId}/result-package` is JSON and includes only files that have
  `artifactManifest`; ordinary ZIPs can be absent. It is not archive retrieval.
- Unscoped `/api/runs` can return `400 PROJECT_SCOPE_REQUIRED`; always supply
  `projectId`. Scope errors can be `WORKSPACE_CONTEXT_REQUIRED` or
  `WORKSPACE_CONTEXT_INCOMPLETE`.
- `401 AMR_AUTH_REQUIRED`: sign in again through the app. `403 WORKSPACE_ACCESS_DENIED`:
  inspect the directory and use an authorized membership. `503
  WORKSPACE_AUTHORITY_UNAVAILABLE`: report the service failure; don't bypass it.
- Missing optional fields are unknown. A successful run may still await input,
  have unfinished work, or lack a validated deliverable.
- A GET workspace listing can perform OpenDesign's own legacy-project binding;
  the helper does not submit mutations or change the user's active workspace.
- Downloads check the advertised inventory size and ZIP directory/marker presence,
  then return a transfer SHA-256. This is not a full package integrity audit.

## Source locations

- [Workspace catalogs and project/file routes](https://github.com/nexu-io/open-design/blob/open-design-v0.25.0/apps/daemon/src/routes/project/index.ts)
- [Workspace directory](https://github.com/nexu-io/open-design/blob/open-design-v0.25.0/apps/daemon/src/routes/collab-context.ts)
- [Membership verification](https://github.com/nexu-io/open-design/blob/open-design-v0.25.0/apps/daemon/src/collab/request-workspace-context.ts)
- [Run routes](https://github.com/nexu-io/open-design/blob/open-design-v0.25.0/apps/daemon/src/routes/runs.ts)
- [Recursive file listing](https://github.com/nexu-io/open-design/blob/open-design-v0.25.0/apps/daemon/src/projects.ts)
- [Ignored directories](https://github.com/nexu-io/open-design/blob/open-design-v0.25.0/apps/daemon/src/project-ignored-dirs.ts)
- [Run contract](https://github.com/nexu-io/open-design/blob/open-design-v0.25.0/packages/contracts/src/api/chat.ts)
