# Tracker workflow configuration

Use `.tracker-workflow.json` at the notes repository root. This is separate from
each tracker's `config.json`, which continues to control rendering only.

```json
{
  "schema_version": 1,
  "projects_dir": "Projects",
  "branch_prefix": "team/docs",
  "hub": {
    "script": "Projects/TrackerHub/build.py",
    "config": "Projects/TrackerHub/config.json",
    "outputs": ["Projects/TrackerHub/catalog.json", "tracker-mindmaps.html"],
    "companion_repository": "example/shared-notes",
    "companion_checkout": "../SharedNotes"
  }
}
```

All fields except `schema_version` are optional when the file exists.
Defaults are `Projects`, `docs`, and the hub paths shown. With no hub build script,
no companion checkout is needed. A hub with only this repository also needs none.
A hub with one external repository can infer its identity from the hub config;
supply its checkout explicitly through config, `TRACKER_WORK_REPO` or `--work`.
The helper currently supports at most one external hub repository. For more,
use the repository's explicit hub build workflow rather than silently omitting
sources. Catalog roots identify sources but are never write destinations.

Repository-contained paths cannot escape by `..` or symlink. A companion checkout
may be outside the notes repository and is resolved against the primary checkout,
including when finishing from its task worktree. A configured companion receives
its own owned input worktree; it is never committed or pushed by the tracker.

Both shell helpers accept `--config FILE`. An explicitly missing config is an
error. Begin accepts `--notes`, `--work`, `--project`, `--date`, `--base`.
Finish accepts `--tracker-dir`, `--work`, `--title`, `--no-push`, `--no-pr`.
`--no-pr` still pushes; use `--no-push` without publication authority.

`TRACKER_BRANCH_PREFIX` overrides the configured prefix; `TRACKER_WT` selects the
ownership helper. `WT_OWNER` is required at begin and must remain the same at
finish. Worktree placement remains governed by the ownership helper's `WT_ROOT`.
The renderer resolves templates relative to its own script location, so no agent
installation path is encoded into project data.

The helper rebuilds only a hub owned by the edited notes repository. If a central
viewer belongs to another repository, first publish the tracker change, then
prepare a separate viewer rebuild in that repository against the selected
published revision. Follow its review process and preserve the pinned commit.
Report the viewer refresh as outstanding until that separate change is prepared;
do not imply this helper updated a viewer elsewhere.
