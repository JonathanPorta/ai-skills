#!/usr/bin/env python3
"""Migrate a tracker that carries its own renderer onto the shared one.

Handles the three shapes found in the notes repository:

* schema 1 (named panel/callout/acceptance keys, `planning` stage, issue URLs as
  strings, task `evidence_note`), whose project-level text lived in the per-tracker
  SVG template rather than the state;
* schema 2 with a renamed third stage (`approval`, `review`) and renamed
  project fields (`map_title`, `root_line_1`, `future_description`, ...);
* schema 2 already in the canonical shape (then only the copies are removed).

Project-level fields are recovered by coordinate: every `{{project.*}}` and
`{{acceptance.*}}` token in the shared SVG template sits at an x/y that the old
template also used, either for a token of its own (looked up in the old state)
or for literal text (taken verbatim). Nothing is invented: a field the old
tracker never had is an error, not a placeholder.

Writes config.json and <slug>-project-state.json, removes the renderer copies,
appends dropped per-task notes to README.md, and re-renders. Review the diff.
"""

import argparse
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

SKILL_ROOT = Path(__file__).resolve().parent.parent
SVG_TEMPLATE = SKILL_ROOT / 'assets' / 'templates' / 'mindmap.svg.template'
RENDER = SKILL_ROOT / 'scripts' / 'render_tracker.py'
STAGES = ('scoping', 'discovery', 'issues', 'implementation', 'testing', 'delivery')
TEXT = re.compile(r'<text x="([0-9.]+)" y="([0-9.]+)"[^>]*>(.*?)</text>', re.S)
TOKEN = re.compile(r'\{\{([^{}]+)\}\}')
ISSUE_URL = re.compile(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)')
DEFAULT_NOTE = 'Issues ✓ means linked, not closed.'
LEGEND_ANCHOR = 'Child nodes show work and evidence.'
REFRESH = '''## Refresh

The renderer is the `tracker` skill from [ai-skills](https://github.com/JonathanPorta/ai-skills/tree/main/skills/tracker), installed once at `~/.claude/skills/tracker`:

```sh
ln -s ~/devel/portaj/ai-skills/skills/tracker ~/.claude/skills/tracker   # once, after cloning ai-skills beside the other repositories
```

Edit `{slug}-project-state.json`, then from this directory:

```sh
python3 ~/.claude/skills/tracker/scripts/render_tracker.py --png     # HTML, SVG and PNG (the PNG needs Inkscape)
python3 ~/.claude/skills/tracker/scripts/render_tracker.py --check   # confirm the outputs match the JSON
```

Or run `/tracker` from the project repository. Commit the tracker, then rebuild TrackerHub (`python3 Projects/TrackerHub/build.py`) so it appears in the combined viewer.
'''


def texts(document):
    return {(m[1], m[2]): m[3] for m in TEXT.finditer(document)}


def lookup(state, dotted):
    value = state
    for key in dotted.split('.'):
        if not isinstance(value, dict) or key not in value:
            raise ValueError('old state has no field ' + dotted)
        value = value[key]
    return value


def resolve_text(body, old_state):
    """An old template text body → the value it displayed, with tokens expanded from the old state."""
    def expand(match):
        name = match[1]
        if name.startswith('@'):
            return ''
        return str(lookup(old_state, name))
    value = TOKEN.sub(expand, body)
    return html.unescape(value).strip(' ·')


def old_caption_label(renderer_source):
    m = re.search(r"snapshot_caption'\s*:\s*f'Status snapshot: \{month\} \{day\.day\} · ([^{']*)\{ref\}'", renderer_source)
    if m:
        return m[1].strip()
    m = re.search(r"Status snapshot: \{month\} \{day\.day\} · ([^{']*)\{", renderer_source)
    return m[1].strip() if m else 'main'


def old_third_stage(renderer_source):
    m = re.search(r"^STAGES\s*=\s*\(([^)]*)\)", renderer_source, re.M)
    if not m:
        return 'issues'
    names = [n.strip().strip("'\"") for n in m[1].split(',') if n.strip()]
    return names[2] if len(names) >= 3 else 'issues'


def convert_issues(value, path):
    if not isinstance(value, list):
        raise ValueError(path + ': github_issues must be a list')
    out = []
    for item in value:
        if isinstance(item, dict) and 'url' in item:
            out.append(item)
            continue
        if isinstance(item, dict) and 'repository' in item and 'number' in item:
            out.append({'repository': item['repository'], 'number': int(item['number']),
                        'url': f"https://github.com/{item['repository']}/issues/{int(item['number'])}"})
            continue
        if isinstance(item, str):
            m = ISSUE_URL.fullmatch(item)
            if not m:
                raise ValueError(f'{path}: not a GitHub issue URL: {item}')
            out.append({'repository': m[1], 'number': int(m[2]), 'url': item})
            continue
        raise ValueError(f'{path}: unrecognised issue entry {item!r}')
    return out


REFRESH_HEADING = re.compile(r'^## (?:Refresh|Update and reproduce|Regenerate|Maintain this snapshot|Reproduce)\b[^\n]*\n', re.M)
NEXT_HEADING = re.compile(r'^## ', re.M)


def rewrite_readme(text, slug, notes):
    """Replace only the old refresh section; keep every other section in place."""
    m = REFRESH_HEADING.search(text)
    if m:
        after = NEXT_HEADING.search(text, m.end())
        end = after.start() if after else len(text)
        text = text[:m.start()] + text[end:]
    text = text.rstrip('\n') + '\n\n'
    if notes:
        text += '## Evidence notes carried from the previous renderer\n\n' + '\n'.join(notes) + '\n\n'
    return text + REFRESH.format(slug=slug)


OLD_COMMANDS = re.compile(r'python3 (?:-m unittest[^\n]*|render_tracker\.py)')


def stale_maintenance_headings(text):
    """Headings of sections (other than the new Refresh) that still run the old local renderer."""
    stale = []
    sections = re.split(r'(?m)^(?=## )', text)
    for section in sections:
        heading = section.split('\n', 1)[0].strip()
        if heading == '## Refresh' or not heading.startswith('## '):
            continue
        if OLD_COMMANDS.search(section):
            stale.append(heading)
    return stale


def migrate(tracker_dir, project_name, slug, dry_run=False):
    tracker_dir = Path(tracker_dir)
    state_path = tracker_dir / f'{slug}-project-state.json'
    old_state = json.loads(state_path.read_text(encoding='utf-8'))
    old_template_path = tracker_dir / 'templates' / 'mindmap.svg.template'
    renderer_path = tracker_dir / 'render_tracker.py'
    old_template = old_template_path.read_text(encoding='utf-8') if old_template_path.exists() else ''
    renderer = renderer_path.read_text(encoding='utf-8') if renderer_path.exists() else ''
    old_texts = texts(old_template)
    skill_texts = texts(SVG_TEMPLATE.read_text(encoding='utf-8'))
    third = old_third_stage(renderer)
    notes = []

    # --- project and acceptance text, by coordinate --------------------------------
    project, acceptance = {'context_panels': {}, 'callouts': {}}, {}
    subtitle_sep = ' · {{@snapshot_caption}}'
    for pos, body in skill_texts.items():
        names = [n for n in TOKEN.findall(body) if n.startswith(('project.', 'acceptance.'))]
        if not names:
            continue
        if len(names) != 1:
            raise ValueError('shared template has a multi-token text at ' + str(pos))
        name = names[0]
        if pos in old_texts:
            old_body = old_texts[pos]
            if name == 'project.subtitle' and subtitle_sep in old_body:
                old_body = old_body.replace(subtitle_sep, '')
            value = resolve_text(old_body, old_state)
        else:
            value = None
            if name == 'project.later_scope':
                value = old_state['project'].get('future_description')
            elif name == 'project.excluded_scope':
                value = old_state['project'].get('excluded_description')
            if value is None:
                raise ValueError(f'cannot recover {name}: the old template has no text at {pos}')
        parts = name.split('.')
        if parts[0] == 'acceptance':
            acceptance.setdefault(parts[1], {})[parts[2]] = value
        elif parts[1] in ('context_panels', 'callouts'):
            project[parts[1]].setdefault(parts[2], {})[parts[3]] = value
        else:
            project[parts[1]] = value
    # Fields the old tracker also kept in state but the shared template takes from state too.
    for key in ('accessible_title', 'description', 'completion_note', 'scoping_note', 'evidence_note', 'sources_note'):
        if key not in project:
            project[key] = old_state['project'][key]
    project = {k: project[k] for k in ('context_panels', 'callouts', 'accessible_title', 'description', 'completion_note',
                                        'scoping_note', 'evidence_note', 'sources_note', 'heading', 'subtitle', 'tagline',
                                        'center_title', 'center_repository', 'center_line_1', 'center_line_2', 'center_line_3',
                                        'center_line_4', 'acceptance_heading', 'later_scope', 'excluded_scope')}
    acceptance = {k: acceptance[k] for k in sorted(acceptance)}

    # --- legend sentence and labels --------------------------------------------------
    issues_label = third.capitalize()
    issues_note = None
    for body in old_texts.values():
        if LEGEND_ANCHOR in body:
            sentence = resolve_text(body.split(LEGEND_ANCHOR)[0], old_state)
            if sentence and sentence != f'{issues_label} ✓ means linked, not closed.':
                issues_note = sentence
    if issues_note is None and 'legend_note' in old_state['project']:
        issues_note = old_state['project']['legend_note']

    # --- workstreams --------------------------------------------------------------------
    workstreams = {}
    for wid, ws in old_state['workstreams'].items():
        stages = {}
        for key, value in ws['stages'].items():
            stages['issues' if key == third else key] = value
        if set(stages) != set(STAGES):
            raise ValueError(f'workstream {wid}: stages {sorted(stages)} do not map onto {STAGES}')
        new_ws = {
            'title': ws['title'], 'repository': ws['repository'], 'status_summary': ws['status_summary'],
            'stages': {s: stages[s] for s in STAGES}, 'evidence_summary': ws['evidence_summary'], 'tasks': {},
        }
        sources = ws.get('sources') or []
        evidence_url = ws.get('evidence_url') or (sources[0] if sources else None)
        if evidence_url:
            new_ws['evidence_url'] = evidence_url
        for extra in sources[1:]:
            notes.append(f'- Workstream {wid} ({ws["title"]}): additional source {extra}')
        for tid, task in ws['tasks'].items():
            new_task = {'title': task['title'], 'description': task['description'], 'status_label': task['status_label'],
                        'color_stage': 'issues' if task['color_stage'] == third else task['color_stage']}
            tsources = task.get('sources') or []
            turl = task.get('evidence_url') or (tsources[0] if tsources else None)
            if turl:
                new_task['evidence_url'] = turl
            new_task['github_issues'] = convert_issues(task.get('github_issues', []), f'workstreams.{wid}.tasks.{tid}')
            if task.get('evidence_note'):
                notes.append(f'- {wid}.{tid} {task["title"]}: {task["evidence_note"]}')
            for extra in tsources[1:]:
                notes.append(f'- {wid}.{tid} {task["title"]}: additional source {extra}')
            new_ws['tasks'][tid] = new_task
        new_ws['github_issues'] = convert_issues(ws.get('github_issues', []), f'workstreams.{wid}')
        workstreams[wid] = new_ws

    snapshot = dict(old_state['snapshot'])
    ref = snapshot['evidence_ref']
    if not re.fullmatch(r'[0-9a-f]{7,40}', ref):
        raise ValueError('snapshot.evidence_ref is not a commit SHA: ' + ref)
    new_state = {'schema_version': 2, 'snapshot': snapshot, 'project': project, 'workstreams': workstreams, 'acceptance': acceptance}
    config = {'workstream_count': len(workstreams), 'project': project_name, 'slug': slug, 'ref_label': old_caption_label(renderer)}
    if issues_label != 'Issues':
        config['issues_label'] = issues_label
    if issues_note:
        config['issues_note'] = issues_note
    # Validate before anything is deleted: the migrated state must render.
    sys.path.insert(0, str(SKILL_ROOT / 'scripts'))
    import render_tracker  # noqa: E402
    render_tracker.render(new_state, config, state_path=state_path)
    if dry_run:
        return new_state, config, notes

    state_path.write_text(json.dumps(new_state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (tracker_dir / 'config.json').write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for p in [*tracker_dir.glob('render_tracker.py'), *tracker_dir.glob('test_*.py'), *tracker_dir.glob('*.schema.json'),
              *tracker_dir.glob('.gitignore')]:
        p.unlink()
    for sub in ('templates', '__pycache__'):
        shutil.rmtree(tracker_dir / sub, ignore_errors=True)
    readme = tracker_dir / 'README.md'
    text = readme.read_text(encoding='utf-8') if readme.exists() else f'# {project_name} project tracker\n'
    rewritten = rewrite_readme(text, slug, notes)
    readme.write_text(rewritten, encoding='utf-8')
    for heading in stale_maintenance_headings(rewritten):
        print(f'README: the section {heading!r} still invokes the old per-directory renderer; edit it by hand', file=sys.stderr)
    result = subprocess.run([sys.executable, str(RENDER), '--tracker-dir', str(tracker_dir)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('render failed after migration: ' + result.stderr.strip())
    return new_state, config, notes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tracker-dir', type=Path, required=True)
    parser.add_argument('--project', required=True, help='Display name, usually the directory above Tracker')
    parser.add_argument('--slug', required=True, help='Existing file stem of <slug>-project-state.json')
    parser.add_argument('--dry-run', action='store_true', help='Print the migrated state and config; write nothing')
    args = parser.parse_args(argv)
    try:
        state, config, notes = migrate(args.tracker_dir, args.project, args.slug, args.dry_run)
    except (OSError, ValueError, KeyError) as exc:
        print('Tracker error: ' + str(exc), file=sys.stderr)
        return 1
    if args.dry_run:
        print(json.dumps({'config': config, 'state': state, 'notes': notes}, indent=2, ensure_ascii=False))
    else:
        print(f'Migrated {args.tracker_dir}: {len(state["workstreams"])} workstreams, {len(notes)} notes carried to README.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
