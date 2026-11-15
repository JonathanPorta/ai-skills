#!/usr/bin/env python3
"""Resolve portable tracker workflow settings without executing configuration."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import sys


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate config key: ' + key)
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)


def relative(value, name):
    if (not isinstance(value, str) or not value or '\\' in value
            or any(ord(c) < 32 for c in value)):
        raise ValueError(name + ' must be a relative path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p) == '.':
        raise ValueError(name + ' must stay inside the notes repository')
    return value


def inside(repo, value, name):
    value = relative(value, name)
    try:
        (repo / value).resolve().relative_to(repo.resolve())
    except ValueError as exc:
        raise ValueError(name + ' escapes through a symlink') from exc
    return value


def settings(repo, config, checkout_root=None):
    data = read(config) if config.exists() else {}
    if not isinstance(data, dict) or set(data) - {'schema_version', 'projects_dir', 'branch_prefix', 'hub'}:
        raise ValueError('unknown tracker workflow settings')
    if config.exists() and (type(data.get('schema_version')) is not int or data['schema_version'] != 1):
        raise ValueError('schema_version must be 1')
    hub = data.get('hub', {})
    if not isinstance(hub, dict) or set(hub) - {'script', 'config', 'outputs', 'companion_repository', 'companion_checkout'}:
        raise ValueError('unknown hub settings')
    prefix = data.get('branch_prefix', 'docs')
    if not isinstance(prefix, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*', prefix):
        raise ValueError('branch_prefix must be slash-separated branch components')
    outputs = hub.get('outputs', ['Projects/TrackerHub/catalog.json', 'tracker-mindmaps.html'])
    if not isinstance(outputs, list) or not outputs:
        raise ValueError('hub.outputs must be a nonempty array')
    outputs = [inside(repo, p, 'hub.outputs') for p in outputs]
    companion = hub.get('companion_checkout', '')
    if not isinstance(companion, str) or any(ord(c) < 32 for c in companion):
        raise ValueError('hub.companion_checkout must be a path')
    repository = hub.get('companion_repository', '')
    if not isinstance(repository, str) or (repository and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)):
        raise ValueError('hub.companion_repository must be owner/name')
    return {
        'tracker_projects_dir': inside(repo, data.get('projects_dir', 'Projects'), 'projects_dir'),
        'tracker_branch_prefix': prefix,
        'tracker_hub_script': inside(repo, hub.get('script', 'Projects/TrackerHub/build.py'), 'hub.script'),
        'tracker_hub_config': inside(repo, hub.get('config', 'Projects/TrackerHub/config.json'), 'hub.config'),
        'tracker_hub_outputs': outputs,
        'tracker_companion_repository': repository,
        'tracker_companion_checkout': str(((checkout_root or repo) / Path(companion).expanduser()).resolve()) if companion else '',
    }


def companion_repository(repo, config, selected):
    hub = read(repo / inside(repo, config, 'hub.config'))
    if not isinstance(hub, dict):
        raise ValueError('hub configuration must be an object')
    entries = hub.get('repositories', [])
    if not isinstance(entries, list):
        raise ValueError('hub repositories must be an array')
    external = []
    for entry in entries:
        # Only inspect roots to identify the local repository. Never create, edit
        # or check out anything at a path taken from the hub catalog.
        if not isinstance(entry, dict) or not isinstance(entry.get('root'), str):
            raise ValueError('invalid hub repository entry')
        root = (repo / config).parent / entry['root']
        if root.resolve() != repo.resolve():
            name = entry.get('repository')
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
                raise ValueError('hub repository must be owner/name')
            external.append(name)
    if selected:
        if selected not in external:
            raise ValueError('configured companion_repository is not an external hub source')
        if len(external) != 1:
            raise ValueError('tracker workflow supports one external hub source; additional sources need an explicit build workflow')
        return selected
    if not external:
        return ''
    if len(external) != 1 or not isinstance(external[0], str):
        raise ValueError('configure exactly one external hub source and its companion checkout')
    return external[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--checkout-root', type=Path)
    parser.add_argument('--project')
    parser.add_argument('--hub-config')
    parser.add_argument('--hub-repository', default='')
    args = parser.parse_args()
    try:
        repo = args.repo.expanduser().resolve()
        if args.config is not None and not args.config.is_file():
            raise ValueError('explicit config does not exist: ' + str(args.config))
        if args.hub_config:
            print(companion_repository(repo, args.hub_config, args.hub_repository))
        else:
            resolved = settings(repo, args.config or repo / '.tracker-workflow.json', args.checkout_root)
            if args.project:
                inside(repo, str(PurePosixPath(resolved['tracker_projects_dir']) / args.project / 'Tracker'), 'tracker directory')
            for key, value in resolved.items():
                if isinstance(value, list):
                    print(key + '=(' + ' '.join(shlex.quote(v) for v in value) + ')')
                else:
                    print(key + '=' + shlex.quote(value))
    except (OSError, ValueError, TypeError) as exc:
        print('Tracker configuration error: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
