#!/usr/bin/env python3
"""Render a project tracker mind map (HTML, SVG, optional PNG) from its JSON state.

Python 3.9+ standard library only. The renderer owns the design: six independent
stage indicators, fixed stage colours and the card geometry. A tracker directory
owns only its state (`<slug>-project-state.json`), `config.json`, README and the
rendered outputs. Edit the state, re-render, and use --check to prove the outputs
match the state byte for byte.
"""

import argparse
from datetime import date
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_ROOT / 'assets' / 'templates'
STAGES = ('scoping', 'discovery', 'issues', 'implementation', 'testing', 'delivery')
COLORS = dict(zip(STAGES, ('#5868AE', '#2581B7', '#B77820', '#8859B9', '#187F7A', '#4B8D45')))
TINTS = dict(zip(STAGES, ('#eef0f7', '#e9f2f8', '#f8f2e9', '#f3eef8', '#e8f2f2', '#edf4ec')))
STATES = {'complete': '✓', 'partial': '◐', 'pending': '—'}
PENDING = '#E7EBF0'
TEXT = '#59677A'
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')
TOKEN = re.compile(r'\{\{([^{}]+)\}\}')
STAGE_BLOCK = re.compile(r'\{\{#stage (\d+) (\w+)\}\}(.*?)\{\{/stage\}\}', re.S)
EVIDENCE_LINK_BLOCK = re.compile(r'\{\{#evidence_links\}\}(.*?)\{\{/evidence_links\}\}', re.S)
WORKSTREAM_EVIDENCE_BLOCK = re.compile(r'\{\{#workstream_evidence (\d+)\}\}(.*?)\{\{/workstream_evidence\}\}', re.S)
TASK_LINK_BLOCK = re.compile(r'\{\{#task_link (\d+) ([\w-]+)\}\}(.*?)\{\{/task_link\}\}', re.S)
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
STATE_SUFFIX = '-project-state.json'
CONFIG_KEYS = ('workstream_count',)
CONFIG_OPTIONAL = ('project', 'slug', 'ref_label', 'issues_label', 'issues_note')


def validate_url(value, path):
    if value is None:
        return
    message = path + ' must be an absolute HTTPS URL without credentials, or null'
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        raise ValueError(message)
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == 'https' and parts.hostname and parts.username is None
                 and parts.password is None and parts.port != 0)
    except ValueError as exc:
        raise ValueError(message) from exc
    if not valid:
        raise ValueError(message)


def lookup(state, path):
    value = state
    for key in path.split('.'):
        try:
            value = value[key]
        except (KeyError, TypeError) as exc:
            raise ValueError('Missing state field: ' + path) from exc
    return value


def keys(value, expected, path, optional=()):
    if not isinstance(value, dict):
        raise ValueError(path + ' must be an object')
    missing, extra = set(expected) - value.keys(), value.keys() - set(expected) - set(optional)
    if missing or extra:
        raise ValueError(f'{path}: missing {sorted(missing)}; unknown {sorted(extra)}')


def validate_issues(value, path):
    if not isinstance(value, list):
        raise ValueError(path + ' must be an array')
    seen = set()
    for index, issue in enumerate(value):
        item_path = f'{path}[{index}]'
        keys(issue, ['repository', 'number', 'url'], item_path)
        repository, number = issue['repository'], issue['number']
        if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError(item_path + '.repository must be owner/repository')
        if type(number) is not int or number < 1:
            raise ValueError(item_path + '.number must be a positive integer')
        expected = f'https://github.com/{repository}/issues/{number}'
        if issue['url'] != expected:
            raise ValueError(item_path + '.url must match the GitHub repository and issue number')
        if expected in seen:
            raise ValueError(item_path + ' duplicates a GitHub issue association')
        seen.add(expected)


def single_line(value, path):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError(path + ' must be a single-line string')


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=no_duplicate_keys)


def validate_config(config, state):
    keys(config, CONFIG_KEYS, 'config', optional=CONFIG_OPTIONAL)
    count = config['workstream_count']
    if type(count) is not int or count < 1:
        raise ValueError('config.workstream_count must be a positive integer')
    if not isinstance(state['workstreams'], dict) or len(state['workstreams']) != count:
        raise ValueError('config.workstream_count must match the number of workstreams; update config and state together')
    for name in CONFIG_OPTIONAL:
        if name in config:
            single_line(config[name], 'config.' + name)
            if not config[name].strip():
                raise ValueError('config.' + name + ' must not be empty')
    if 'slug' in config and not SLUG.fullmatch(config['slug']):
        raise ValueError('config.slug must be lower-case letters, digits and single hyphens')


def project_name(state, config):
    return config.get('project') or state['project']['heading'].split(' · ')[0].strip()


def tracker_slug(config, state_path=None):
    if config.get('slug'):
        return config['slug']
    if state_path is not None and state_path.name.endswith(STATE_SUFFIX):
        candidate = state_path.name[: -len(STATE_SUFFIX)]
        if SLUG.fullmatch(candidate):
            return candidate
    raise ValueError('config.slug is required when the state file is not named <slug>' + STATE_SUFFIX)


def shift(fragment, dx=0, dy=0):
    """Place reference card fragments without changing their visual attributes."""
    return re.sub(r'\b(x|y)="(-?[0-9.]+)"',
                  lambda m: m[1] + '="' + format(float(m[2]) + (dx if m[1] == 'x' else dy), '.15g') + '"', fragment)


def ordered_workstreams(state):
    """Keep graph and focus order stable across JSON object serialization."""
    return sorted(state['workstreams'].items(), key=lambda item: (int(item[0]), item[0]))


def graph_template(state, template_dir):
    parent = (template_dir / 'parent.svg.template').read_text(encoding='utf-8')
    task = (template_dir / 'task.svg.template').read_text(encoding='utf-8')
    workstreams = ordered_workstreams(state)
    split = len(workstreams) // 2
    sides = [workstreams[:split], workstreams[split:]]
    heights = [[max(226, 87 * len(ws['tasks']) - 11) for _, ws in side] for side in sides]
    totals = [sum(h) + 70 * max(0, len(h) - 1) for h in heights]
    # The minimum body includes the central guidance panels. Larger graphs grow
    # vertically; there is no workstream or child-card ceiling.
    body_height = max(2911, *totals)
    growth = body_height - 2911
    center_y = 1870 + growth / 2
    connectors, groups = [], []
    for index, (side, sizes, total) in enumerate(zip(sides, heights, totals)):
        px, tx = (1020, 80) if index == 0 else (2600, 3240)
        top = 509 + (body_height - total) / 2
        for (wid, ws), height in zip(side, sizes):
            cy = top + height / 2
            parent_y = cy - 113
            task_y = cy - max(0, 87 * len(ws['tasks']) - 11) / 2
            start, bend, end = (1820, 1730, 1600) if index == 0 else (2380, 2470, 2600)
            connectors.append(f'<path d="M {start} {center_y:g} C {bend} {center_y:g}, {bend} {cy:g}, {end} {cy:g}" fill="none" stroke="#CBD3DF" stroke-width="3"/>')
            fx = 60 if index == 0 else 2580
            group = [f'<g class="focus-node" data-node="{wid}" data-focus="{fx},{top-24:g},1560,{height+48:g}">']
            for n, tid in enumerate(ws['tasks']):
                yy = task_y + n * 87
                edge, bend, end = (1020, 990, 960) if index == 0 else (3180, 3210, 3240)
                group.append(f'<path d="M {edge} {cy:g} C {bend} {cy:g}, {bend} {yy+38:g}, {end} {yy+38:g}" fill="none" stroke="#CBD3DF" stroke-width="2"/>')
            group.append(shift(parent, px, parent_y).replace('{{@wid}}', wid))
            for n, tid in enumerate(ws['tasks']):
                fragment = shift(task, tx, task_y + n * 87)
                group.append(fragment.replace('{{@wid}}', wid).replace('{{@tid}}', tid))
            group.append('</g>')
            groups.extend(group)
            top += height + 70
    return '\n'.join(connectors + groups), growth


def validate(state, config, template_dir=TEMPLATES):
    """Validate configured workstreams and explicit, independent stage values."""
    keys(state, ['schema_version', 'snapshot', 'project', 'workstreams', 'acceptance'], 'state')
    if type(state['schema_version']) is not int or state['schema_version'] != 2:
        raise ValueError('Unsupported schema_version')
    snap = state['snapshot']
    keys(snap, ['date', 'evidence_ref', 'extracted_from'], 'snapshot')
    if not isinstance(snap['date'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', snap['date']):
        raise ValueError('snapshot.date must be YYYY-MM-DD')
    date.fromisoformat(snap['date'])
    if not isinstance(snap['evidence_ref'], str) or not re.fullmatch(r'[0-9a-f]{7,40}', snap['evidence_ref']):
        raise ValueError('snapshot.evidence_ref must be a 7–40 character commit SHA')
    keys(snap['extracted_from'], ['repository', 'commit', 'path'], 'snapshot.extracted_from')
    for key, value in snap['extracted_from'].items():
        if not isinstance(value, str) or not value:
            raise ValueError('snapshot.extracted_from.' + key + ' must be a nonempty string')
    template_dir = Path(template_dir)
    validate_config(config, state)
    for wid, ws in state['workstreams'].items():
        if not isinstance(wid, str) or not re.fullmatch(r'[0-9]+', wid):
            raise ValueError('Workstream IDs must be numeric strings')
        keys(ws, ['title', 'repository', 'status_summary', 'stages', 'evidence_summary', 'tasks', 'github_issues'],
             'workstreams.' + wid, optional=('evidence_url',))
        validate_url(ws.get('evidence_url'), f'workstreams.{wid}.evidence_url')
        validate_issues(ws['github_issues'], f'workstreams.{wid}.github_issues')
        keys(ws['stages'], STAGES, 'workstreams.' + wid + '.stages')
        for stage, status in ws['stages'].items():
            if not isinstance(status, str) or status not in STATES:
                raise ValueError(f'workstreams.{wid}.stages.{stage}: expected complete, partial or pending')
        if not isinstance(ws['tasks'], dict):
            raise ValueError('workstreams.' + wid + '.tasks must be an object')
        for name in ('title', 'repository', 'status_summary', 'evidence_summary'):
            single_line(ws[name], f'workstreams.{wid}.{name}')
        for tid, task in ws['tasks'].items():
            if not isinstance(tid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', tid):
                raise ValueError('Task IDs must contain letters, numbers, underscores or hyphens')
            keys(task, ['title', 'description', 'status_label', 'color_stage', 'github_issues'], f'workstreams.{wid}.tasks.{tid}', optional=('evidence_url',))
            for name in ('title', 'description', 'status_label'):
                single_line(task[name], f'workstreams.{wid}.tasks.{tid}.{name}')
            validate_url(task.get('evidence_url'), f'workstreams.{wid}.tasks.{tid}.evidence_url')
            validate_issues(task['github_issues'], f'workstreams.{wid}.tasks.{tid}.github_issues')
            if not isinstance(task['color_stage'], str) or task['color_stage'] not in (*STAGES, 'pending'):
                raise ValueError(f'workstreams.{wid}.tasks.{tid}.color_stage: unknown stage')
    # Derive non-workstream text-field shape from the stable templates. Catch misspellings
    # and missing summaries instead of silently keeping stale text in the graphic.
    direct_paths = set()
    for filename in ('mindmap.svg.template', 'mindmap.html.template'):
        for name in TOKEN.findall((template_dir / filename).read_text(encoding='utf-8')):
            if name.startswith(('project.', 'workstreams.', 'acceptance.')):
                direct_paths.add(name)
    for path in direct_paths:
        value = lookup(state, path)
        if not isinstance(value, str) or '\n' in value or '\r' in value or any(ord(c) < 32 for c in value):
            raise ValueError(path + ' must be a single-line string')
    for prefix in ('project', 'acceptance'):
        def check_shape(value, path):
            descendants = {p[len(path) + 1:].split('.')[0] for p in direct_paths if p.startswith(path + '.')}
            if descendants:
                keys(value, descendants, path)
                for key in descendants:
                    check_shape(value[key], path + '.' + key)
        check_shape(state[prefix], prefix)


def render(state, config, template_dir=TEMPLATES, state_path=None):
    validate(state, config, template_dir)
    template_dir = Path(template_dir)
    snapshot = state['snapshot']
    day = date.fromisoformat(snapshot['date'])
    month = MONTHS[day.month - 1]
    ref = snapshot['evidence_ref']
    ref_label = config.get('ref_label', 'main')
    issues_name = config.get('issues_label', 'Issues')
    derived = {
        '@project': project_name(state, config),
        '@slug': tracker_slug(config, state_path),
        '@issues_name': issues_name,
        '@issues_chip': issues_name.upper(),
        '@issues_note': config.get('issues_note', issues_name + ' ✓ means linked, not closed.'),
        '@snapshot_caption': f'Status snapshot: {month} {day.day} · {ref_label} {ref}',
        '@snapshot_footer': 'SNAPSHOT ' + ref,
        '@html_snapshot': f'{day.day} {month[:3]} {day.year} · {ref_label} {ref}',
    }
    for wid, ws in state['workstreams'].items():
        if ws['github_issues']:
            issue = ws['github_issues'][0]
            derived['@issue_url.' + wid] = issue['url']
            derived['@issue_label.' + wid] = f'Open GitHub issue {issue["repository"]}#{issue["number"]} for workstream {wid}: {ws["title"]} (opens in a new tab)'
        if ws.get('evidence_url'):
            derived['@evidence_url.' + wid] = ws['evidence_url']
            derived['@evidence_label.' + wid] = f'Open evidence for workstream {wid}: {ws["title"]} (opens in a new tab)'
        completed = [s for s in STAGES if ws['stages'][s] == 'complete']
        parent_stage = completed[-1] if completed else 'pending'
        derived['@parent_fill.' + wid] = TINTS.get(parent_stage, PENDING)
        derived['@parent_accent.' + wid] = COLORS.get(parent_stage, TEXT)
        for tid, task in ws['tasks'].items():
            if task['github_issues']:
                issue = task['github_issues'][0]
                derived[f'@issue_url.{wid}.{tid}'] = issue['url']
                derived[f'@issue_label.{wid}.{tid}'] = f'Open GitHub issue {issue["repository"]}#{issue["number"]} for {task["title"]} (opens in a new tab)'
            derived[f'@task_fill.{wid}.{tid}'] = TINTS.get(task['color_stage'], PENDING)
            derived[f'@task_accent.{wid}.{tid}'] = COLORS.get(task['color_stage'], TEXT)
            if task.get('evidence_url'):
                derived[f'@evidence_url.{wid}.{tid}'] = task['evidence_url']
                derived[f'@evidence_label.{wid}.{tid}'] = f'Open evidence for {task["title"]} (opens in a new tab)'

    def link(kind, key, body):
        return (f'<a data-{kind}-link="{key}" href="{{{{@{kind}_url.{key}}}}}" '
                f'target="_blank" rel="noopener noreferrer" aria-label="{{{{@{kind}_label.{key}}}}}">'
                f'<title>{{{{@{kind}_label.{key}}}}}</title>{body}</a>')

    def task_link_block(match):
        wid, tid, body = match.groups()
        task = state['workstreams'][wid]['tasks'][tid]
        key = f'{wid}.{tid}'
        if task['github_issues']:
            if task.get('evidence_url'):
                # Preserve every visible shape and coordinate. The existing status
                # label becomes a separate source link; the card opens its issue.
                body, status = body.rsplit('<text ', 1)
                return link('issue', key, body) + link('evidence', key, '<text ' + status)
            return link('issue', key, body)
        return link('evidence', key, body) if task.get('evidence_url') else body

    def workstream_evidence_block(match):
        wid, body = match.groups()
        return link('evidence', wid, body) if state['workstreams'][wid].get('evidence_url') else body

    def stage_block(match):
        wid, stage, body = match.groups()
        status = state['workstreams'][wid]['stages'][stage]
        rect = body.split('\n', 1)[0]
        # Keep every original coordinate, float representation, attribute and space.
        hatch = rect.replace('{{fill}}', 'url(#hatch)') + '\n' if status == 'partial' else ''
        values = {
            'fill': COLORS[stage] if status == 'complete' else TINTS[stage] if status == 'partial' else PENDING,
            'text_fill': '#FFFFFF' if status == 'complete' else TEXT,
            'symbol': STATES[status],
            'hatch': hatch,
            '@issues_chip': derived['@issues_chip'],
        }
        rendered = TOKEN.sub(lambda m: html.escape(values[m[1]], quote=True) if m[1] == '@issues_chip' else values[m[1]], body)
        if stage == 'issues' and state['workstreams'][wid]['github_issues']:
            rendered = link('issue', wid, rendered)
        return rendered

    def substitute(match):
        # Every value is user-controlled and may land in text or an attribute;
        # escape quotes as well as markup in all contexts.
        name = match[1]
        value = derived[name] if name.startswith('@') else lookup(state, name)
        return html.escape(value, quote=True)

    graph, growth = graph_template(state, template_dir)
    derived.update({'@height': format(3980 + growth, 'g'), '@center_shift': format(growth / 2, 'g'), '@footer_shift': format(growth, 'g')})
    svg_template = (template_dir / 'mindmap.svg.template').read_text(encoding='utf-8').replace('{{@graph}}', graph)
    svg = TOKEN.sub(substitute, WORKSTREAM_EVIDENCE_BLOCK.sub(workstream_evidence_block, TASK_LINK_BLOCK.sub(task_link_block, STAGE_BLOCK.sub(stage_block, svg_template))))
    web_template = (template_dir / 'mindmap.html.template').read_text(encoding='utf-8')
    options = ''.join(f'<option value="{wid}">{wid} · {html.escape(ws["title"], quote=True)}</option>' for wid, ws in ordered_workstreams(state))
    has_links = any(ws.get('evidence_url') or ws['github_issues'] or any(t.get('evidence_url') or t['github_issues'] for t in ws['tasks'].values())
                    for ws in state['workstreams'].values())
    web_template = EVIDENCE_LINK_BLOCK.sub(lambda m: m[1] if has_links else '', web_template)
    # Substitute user text once. Braces within content never become executable tokens.
    web = TOKEN.sub(lambda m: svg.rstrip('\n') if m[1] == 'svg' else options if m[1] == '@focus_options' else substitute(m), web_template)
    return {'.svg': svg, '.html': web}


def locate_state(tracker_dir, config):
    """The one state file in a tracker directory: <slug>-project-state.json."""
    if config.get('slug'):
        return tracker_dir / (config['slug'] + STATE_SUFFIX)
    candidates = sorted(p for p in tracker_dir.glob('*' + STATE_SUFFIX))
    if len(candidates) != 1:
        raise ValueError(f'{tracker_dir}: expected exactly one *{STATE_SUFFIX}; found {len(candidates)}. Set config.slug to choose.')
    return candidates[0]


def export_png(svg):
    inkscape = shutil.which('inkscape')
    if inkscape is None:
        raise ValueError('--png requires Inkscape on PATH')
    result = subprocess.run(
        [inkscape, '--pipe', '--export-type=png', '--export-area-page',
         '--export-dpi=96', '--export-filename=-'],
        input=svg.encode('utf-8'), capture_output=True, timeout=120,
    )
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Inkscape PNG export failed: ' + result.stderr.decode('utf-8', errors='replace'))
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tracker-dir', type=Path, default=Path.cwd(), help='Directory holding config.json and <slug>-project-state.json (default: cwd)')
    parser.add_argument('--state', type=Path, help='State file (default: the one *-project-state.json in --tracker-dir)')
    parser.add_argument('--config', type=Path, help='Config file (default: --tracker-dir/config.json)')
    parser.add_argument('--output-dir', type=Path, help='Where to write outputs (default: --tracker-dir)')
    parser.add_argument('--templates', type=Path, default=TEMPLATES, help='Template directory (default: the skill templates)')
    parser.add_argument('--check', action='store_true', help='Verify HTML/SVG are current without writing')
    parser.add_argument('--png', action='store_true', help='Also render PNG; requires Inkscape on PATH')
    args = parser.parse_args(argv)
    if args.check and args.png:
        parser.error('--check and --png cannot be combined')
    try:
        tracker_dir = args.tracker_dir.resolve()
        config = load_json(args.config or tracker_dir / 'config.json')
        state_path = (args.state or locate_state(tracker_dir, config)).resolve()
        output_dir = args.output_dir or tracker_dir
        state = load_json(state_path)
        rendered = render(state, config, args.templates, state_path)
        stem = tracker_slug(config, state_path) + '-project-mindmap'
        png = export_png(rendered['.svg']) if args.png else None
        if args.check:
            stale = [suffix for suffix, content in rendered.items()
                     if not (output_dir / (stem + suffix)).exists()
                     or (output_dir / (stem + suffix)).read_bytes() != content.encode('utf-8')]
            if stale:
                raise ValueError('Generated files differ: ' + ', '.join(stale))
            print('HTML and SVG match JSON and templates byte for byte.'
                  + (' The PNG is not verified by --check; re-render with --png before publishing.'
                     if (output_dir / (stem + '.png')).exists() else ''))
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            for suffix, content in rendered.items():
                (output_dir / (stem + suffix)).write_bytes(content.encode('utf-8'))
            if png is not None:
                (output_dir / (stem + '.png')).write_bytes(png)
            print('Generated HTML and SVG' + (' and PNG.' if png is not None else '. Use --png to refresh the PNG preview.'))
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print('Tracker error: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
