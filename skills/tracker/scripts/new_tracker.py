#!/usr/bin/env python3
"""Scaffold a new tracker directory from the example state.

Writes config.json, <slug>-project-state.json, README.md and .gitignore into the
target directory. Every text field is a placeholder the agent must replace with
evidence before rendering; the renderer will accept the scaffold as-is, so the
review burden is on the content, not the shape.
"""

import argparse
import json
from pathlib import Path
import re
import sys

SKILL_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = SKILL_ROOT / 'assets' / 'example' / 'example-project-state.json'
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')

README = '''# {project} project tracker

**Snapshot: {date}.** Replace this paragraph with the current position: what has shipped, what is in progress, and what is blocked, with PR and issue numbers.

**Next:** the one or two concrete things that move the project.

## Open the map

- [Interactive mindmap]({slug}-project-mindmap.html): download and open it locally.
- [SVG]({slug}-project-mindmap.svg) · [PNG]({slug}-project-mindmap.png)
- [Editable state]({slug}-project-state.json)

![{project} project mindmap]({slug}-project-mindmap.png)

The map uses the shared tracker renderer from the `tracker` skill: six stage indicators per workstream and five acceptance gates.

**How to read it:**
- ✓ means the stage is complete, ◐ partial and — pending.
- For **{issues_label}**, ✓ means the remaining work has open GitHub issues, not that they're closed. Shipped work needs no retrospective issue, so finished workstreams show —.
- Stage colours show the kind of work, not a percentage.

## Workstreams

| # | Workstream | State | Evidence |
|---|---|---|---|
{rows}

## Refresh

Edit `{slug}-project-state.json`, then from this directory run the `tracker` skill renderer:

```sh
python3 "$TRACKER_SKILL/scripts/render_tracker.py" --png     # HTML, SVG and PNG (the PNG needs Inkscape)
python3 "$TRACKER_SKILL/scripts/render_tracker.py" --check   # confirm the outputs match the JSON
```

Commit the tracker, then rebuild TrackerHub (`python3 Projects/TrackerHub/build.py`) so it appears in the combined viewer.
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tracker-dir', type=Path, required=True, help='Directory to create, e.g. Projects/<Name>/Tracker')
    parser.add_argument('--project', required=True, help='Display name, e.g. "porta.codes"')
    parser.add_argument('--slug', required=True, help='File stem, lower-case with hyphens, e.g. porta-codes')
    parser.add_argument('--repository', required=True, help='Anchor repository owner/name for the snapshot')
    parser.add_argument('--commit', required=True, help='Full 40-character SHA the snapshot is read from')
    parser.add_argument('--path', default='README.md', help='A committed file in the anchor repository (default README.md)')
    parser.add_argument('--date', required=True, help='Snapshot date YYYY-MM-DD')
    parser.add_argument('--workstreams', type=int, default=2, help='Number of workstream placeholders (default 2)')
    parser.add_argument('--ref-label', default='main', help="Caption words before the ref, e.g. 'kioskit main'")
    parser.add_argument('--issues-label', default='Issues', help='Display name of the third stage')
    args = parser.parse_args(argv)
    try:
        if not SLUG.fullmatch(args.slug):
            raise ValueError('--slug must be lower-case letters, digits and single hyphens')
        if not re.fullmatch(r'[0-9a-f]{40}', args.commit):
            raise ValueError('--commit must be a full 40-character SHA')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date):
            raise ValueError('--date must be YYYY-MM-DD')
        if args.workstreams < 1:
            raise ValueError('--workstreams must be at least 1')
        target = args.tracker_dir
        if target.exists() and any(target.iterdir()):
            raise ValueError(f'{target} already exists and is not empty; edit the existing tracker instead')
        state = json.loads(EXAMPLE.read_text(encoding='utf-8'))
        state['snapshot'] = {'date': args.date, 'evidence_ref': args.commit[:7],
                             'extracted_from': {'repository': args.repository, 'commit': args.commit, 'path': args.path}}
        project = state['project']
        project.update({
            'heading': f'{args.project} · Project Mindmap',
            'subtitle': 'TODO: phase → phase → phase',
            'tagline': 'TODO: one-line principle.',
            'center_title': args.project.upper(),
            'center_repository': args.repository,
            'accessible_title': f'{args.project} project map: TODO',
            'description': 'TODO: one sentence describing the workstreams.',
            'acceptance_heading': 'ACCEPTANCE GATES · 0 OF 5 ACCEPTED',
        })
        for key in ('center_line_1', 'center_line_2', 'center_line_3', 'center_line_4', 'completion_note', 'scoping_note',
                    'evidence_note', 'sources_note', 'later_scope', 'excluded_scope'):
            project[key] = 'TODO ' + key.replace('_', ' ')
        for panel in project['context_panels'].values():
            for line in ('line_1', 'line_2', 'line_3'):
                panel[line] = 'TODO'
        for callout in project['callouts'].values():
            for line in [k for k in callout if k.startswith('line_')]:
                callout[line] = 'TODO'
        template_ws = state['workstreams']['02']
        state['workstreams'] = {}
        for n in range(1, args.workstreams + 1):
            ws = json.loads(json.dumps(template_ws))
            ws.update({'title': f'TODO workstream {n}', 'repository': args.repository, 'status_summary': 'TODO',
                       'evidence_summary': 'TODO', 'github_issues': []})
            ws.pop('evidence_url', None)
            ws['stages'] = {s: 'pending' for s in ('scoping', 'discovery', 'issues', 'implementation', 'testing', 'delivery')}
            for task in ws['tasks'].values():
                task.update({'title': 'TODO', 'description': 'TODO', 'status_label': 'TODO', 'color_stage': 'pending', 'github_issues': []})
                task.pop('evidence_url', None)
            state['workstreams'][f'{n:02d}'] = ws
        for gate in state['acceptance'].values():
            gate.update({'description': 'TODO', 'status_label': 'PENDING'})
        config = {'workstream_count': args.workstreams, 'project': args.project, 'slug': args.slug,
                  'ref_label': args.ref_label, 'issues_label': args.issues_label}
        target.mkdir(parents=True, exist_ok=True)
        (target / 'config.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        (target / (args.slug + '-project-state.json')).write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        rows = '\n'.join(f'| {n:02d} | TODO | TODO | TODO |' for n in range(1, args.workstreams + 1))
        (target / 'README.md').write_text(README.format(project=args.project, slug=args.slug, date=args.date,
                                                        issues_label=args.issues_label, rows=rows), encoding='utf-8')
        (target / '.gitignore').write_text('__pycache__/\n*.pyc\n', encoding='utf-8')
        print(f'Scaffolded {target}. Replace every TODO, then render.')
    except (OSError, ValueError) as exc:
        print('Tracker error: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
