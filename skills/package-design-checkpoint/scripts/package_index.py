#!/usr/bin/env python3
"""Build the offline package guide. Keep the two skill-local copies identical."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, unquote, urlsplit


GENERATED_PATHS = {"index.html", "README.md", "artifact-manifest.json", "_package/verification.json"}
METADATA_FIELDS = {"primary", "review_targets", "review_checklist", "decisions", "blockers", "withheld", "lifecycle", "package_map", "verification", "deployment"}
ROLES = {"deployable", "review-only", "source", "documentation", "evidence"}


def _object(value, allowed, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    extra = set(value) - set(allowed)
    if extra:
        raise ValueError(f"unknown {field} field(s): {', '.join(sorted(extra))}")
    return value


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    if any(ord(char) < 32 and char not in "\n\t\r" for char in value):
        raise ValueError(f"{field} contains control characters")
    return " ".join(value.split())


def _list(value, field):
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    return list(value)


def _strings(value, field):
    return [_text(item, field) for item in _list(value, field)]


def _path(value, field, *, directory=False, allow_root=False):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must name a project-relative path")
    if allow_root and value in {".", "./"}:
        return "."
    clean = value.rstrip("/") if directory else value
    if (not clean or clean.startswith("/") or "\\" in clean or
            any(ord(char) < 32 or ord(char) == 127 for char in clean) or
            any(part in {"", ".", ".."} for part in clean.split("/")) or
            ":" in clean):
        raise ValueError(f"{field} must be a safe relative path: {value!r}")
    return clean


def _source_file(value, paths, field):
    path = _path(value, field)
    if path not in paths:
        raise ValueError(f"{field} does not exist in the package payload: {path}")
    return path


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate package metadata key: {key}")
        result[key] = value
    return result


def load_metadata(path):
    if path is None:
        return {}
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle, object_pairs_hook=_no_duplicates)
    return _object(data, METADATA_FIELDS, "package metadata")


def _target(value, paths, field, *, primary=False):
    row = _object(value, {"path", "label", "description", "role"}, field)
    path = _source_file(row.get("path"), paths, field + ".path")
    label = _text(row.get("label"), field + ".label")
    role = row.get("role", "primary" if primary else "alternate")
    allowed = {"primary"} if primary else {"alternate", "evidence", "source"}
    if not isinstance(role, str) or role not in allowed:
        raise ValueError(f"invalid {field}.role: {role}")
    return {"path": "project/" + path, "label": label,
            "description": _text(row.get("description", f"Open {label}."), field + ".description"),
            "role": role}


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _href(path):
    return quote(path, safe="/")


def _link(path, label, class_name=""):
    css = f' class="{class_name}"' if class_name else ""
    return f'<a href="{_href(path)}"{css}>{escape(label)}</a>'


def _rows(values):
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in values) + "</ul>" if values else '<p class="empty">None</p>'


STYLE = """
:root{color-scheme:light;--ink:#202927;--muted:#52615c;--paper:#f4f5f0;--card:#fff;--line:#d7ddd4;--green:#244d3e;--amber:#6e4b12;--purple:#654583}
*{box-sizing:border-box}html{scroll-behavior:auto}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:#205a82;text-decoration-thickness:1px;text-underline-offset:3px}a:visited{color:var(--purple)}a:hover{color:#143c59;text-decoration-thickness:2px}a:focus-visible{outline:3px solid #1b6cb0;outline-offset:5px;border-radius:2px}.skip{position:absolute;top:-100px;left:20px;background:white;padding:10px 16px;z-index:2}.skip:focus{top:16px}.shell{max-width:1120px;padding:42px 32px 64px;margin:auto}.masthead{display:flex;justify-content:space-between;gap:20px;align-items:center;padding-bottom:24px;border-bottom:1px solid var(--line);font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}.wordmark{font-weight:750;letter-spacing:.16em}.masthead span:last-child{text-align:right}.identity{padding:44px 0 32px}.eyebrow,.section-label{font-size:.74rem;font-weight:750;letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}h1{font-size:clamp(2.1rem,5vw,3.65rem);line-height:1.12;letter-spacing:-.045em;margin:12px 0 20px;max-width:900px;overflow-wrap:anywhere}h2{font-size:1.38rem;letter-spacing:-.025em;line-height:1.3;margin:0 0 16px}h3{font-size:1rem;margin:0 0 9px}p{margin:0 0 14px}.meta{display:flex;flex-wrap:wrap;gap:9px 20px;color:var(--muted);font-size:.9rem}.badges{display:flex;flex-wrap:wrap;gap:9px;margin-top:22px}.badge{display:inline-block;padding:5px 11px;border:1px solid var(--line);border-radius:6px;font-size:.76rem;font-weight:700;background:#fff}.posture{color:var(--amber);background:#fbf1dc;border-color:#ddca9d}.posture.ready{color:var(--green);background:#e8f1e9;border-color:#afc4b2}.guide{display:grid;gap:18px}.panel{padding:27px 30px;background:var(--card);border:1px solid var(--line);border-radius:12px;min-width:0}.section-heading{display:flex;gap:15px;align-items:baseline}.step{font-size:.78rem;color:var(--muted);font-variant-numeric:tabular-nums;min-width:22px}.start{background:#e8eeE5;border-color:#b7c6b4;padding:30px}.start h2{font-size:1.7rem;margin-bottom:10px}.start p{max-width:740px}.primary{display:inline-flex;align-items:center;gap:18px;min-height:48px;background:var(--green);border:1px solid var(--green);color:white!important;border-radius:7px;padding:12px 20px;font-weight:650;text-decoration:none;margin:8px 0 10px;overflow-wrap:anywhere}.primary:visited{background:#433b59;border-color:#433b59}.primary:hover{background:#15372a;border-color:#15372a;text-decoration:underline}.primary:focus-visible{outline-offset:5px}.path{display:block;font-size:.8rem;color:var(--muted);overflow-wrap:anywhere}.small{font-size:.86rem;color:var(--muted)}.summary{font-size:1.08rem;max-width:850px}.checklist{margin:0 0 22px;padding-left:24px}.checklist li{padding:3px 0 4px 5px}.target-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.target{border:1px solid var(--line);padding:17px 18px;border-radius:7px;background:#fcfdfb}.target .role{display:block;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:5px}.target p{font-size:.9rem;margin:6px 0 0;color:var(--muted)}.decisions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}.decisions ul{margin:0;padding-left:19px}.empty{color:var(--muted);font-style:italic;margin:0}.map{list-style:none;margin:16px 0 0;padding:0}.map li{display:grid;grid-template-columns:minmax(150px,.8fr) minmax(0,1.4fr);gap:20px;border-top:1px solid var(--line);padding:15px 0}.map code{font-size:.83rem;overflow-wrap:anywhere}.map .kind{display:block;text-transform:uppercase;font-size:.64rem;font-weight:750;letter-spacing:.1em;color:var(--muted);margin-top:3px}.map p{font-size:.88rem;margin:0}.map .source-row{padding-left:18px}.verification{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.result{border-left:3px solid #9aaca1;padding-left:16px}.result strong{display:block;font-size:.91rem;margin-bottom:4px}.result p{font-size:.9rem;margin-bottom:7px}.doc-links{display:flex;flex-wrap:wrap;gap:10px 28px;padding:0;list-style:none;margin:0}.doc-links li{max-width:100%}.doc-links small{display:block;color:var(--muted);font-size:.8rem}.foot{margin-top:25px;display:flex;justify-content:space-between;gap:20px;font-size:.8rem;color:var(--muted)}code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}ul,ol{overflow-wrap:anywhere}@media(max-width:680px){.shell{padding:24px 18px 40px}.masthead{align-items:flex-start;font-size:.67rem;gap:15px}.identity{padding:30px 0 25px}.panel,.start{padding:23px 20px}.target-grid,.decisions,.verification{grid-template-columns:1fr}.decisions{gap:20px}.map li{grid-template-columns:1fr;gap:5px}.map .source-row{padding-left:12px}.section-heading{gap:10px}.foot{display:block}.foot span{display:block;margin-bottom:4px}.primary{display:flex;width:100%;justify-content:space-between}.meta{gap:5px 14px}}@media print{body{background:white}.shell{max-width:none;padding:0}.panel{break-inside:avoid}.primary{color:#244d3e!important;background:white}.skip{display:none}}
"""


def _html(data):
    project = data["project"]
    primary = data["primary"]
    deployment = data["deployment"]
    kind = data["artifact_type"]
    title = f'{project["name"]} — {kind.title()} {data["version"]}'
    posture = {"review-only": "REVIEW ONLY — DO NOT DEPLOY", "implementation-ready": "ACCEPTED — IMPLEMENTATION READY", "deployable": "DEPLOYMENT APPROVED — DESIGNATED SUBTREE ONLY"}[deployment["posture"]]
    targets = [primary, *data["review_targets"]]
    target_html = "".join('<article class="target"><span class="role">' + escape(row["role"]) + '</span>' + _link(row["path"], row["label"]) + '<p>' + escape(row["description"]) + '</p></article>' for row in targets)
    map_html = []
    for row in data["package_map"]:
        label = '<code>' + escape(row["path"]) + '</code>'
        if not row["path"].endswith("/"):
            label = _link(row["path"], row["path"])
        nested = ' class="source-row"' if row["path"].startswith("project/") and row["path"] != "project/" else ""
        map_html.append(f'<li{nested}><div>{label}<span class="kind">{escape(row["role"])}</span></div><p>{escape(row["description"])}</p></li>')
    verification = data["verification"]
    reported = "Not run / not reported" if verification["status"] == "not-run" else verification["status"].title() + " (caller-reported)"
    evidence = _link(verification["evidence"], "Read project verification evidence") if verification.get("evidence") else '<span class="small">No project verification evidence supplied.</span>'
    docs = "".join('<li>' + _link(row["path"], row["label"]) + '<small>' + escape(row["description"]) + '</small></li>' for row in data["documentation"])
    checklist = "".join('<li>' + escape(value) + '</li>' for value in data["review_checklist"])
    namespace = f'<span>Namespace: {escape(project["namespace"])}</span>' if project["namespace"] else ""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>{escape(title)}</title><style>{STYLE}</style></head>
<body><a class="skip" href="#main">Skip to package guide</a><div class="shell">
<div class="masthead"><span class="wordmark">Package guide</span><span>Offline · Self-contained · Versioned</span></div>
<header class="identity"><div class="eyebrow">{escape(kind.upper())} / ARTIFACT IDENTITY</div><h1>{escape(project["name"])}</h1><div class="meta"><span>Version {escape(data["version"])}</span><span>Created {escape(data["created_at"])}</span>{namespace}</div><div class="badges"><span class="badge">{escape(data["lifecycle"])}</span><span class="badge posture {'ready' if deployment['posture'] != 'review-only' else ''}">{posture}</span></div></header>
<main id="main" class="guide">
<section class="panel start" aria-labelledby="start-title"><div class="section-label">02 / Start here</div><h2 id="start-title">Your first stop</h2><p>{escape(primary["description"])}</p>{_link(primary["path"], primary["label"] + " →", "primary")}<span class="path">{escape(primary["path"])}</span></section>
<section class="panel" aria-labelledby="changed-title"><div class="section-heading"><span class="step">03</span><h2 id="changed-title">What changed</h2></div><p class="summary">{escape(data["change"])}</p></section>
<section class="panel" aria-labelledby="review-title"><div class="section-heading"><span class="step">04</span><h2 id="review-title">What to review</h2></div><ol class="checklist">{checklist}</ol><div class="target-grid">{target_html}</div></section>
<section class="panel" aria-labelledby="decisions-title"><div class="section-heading"><span class="step">05</span><h2 id="decisions-title">Current decisions / blockers</h2></div><div class="decisions"><div><h3>Decisions needed</h3>{_rows(data["decisions"])}</div><div><h3>Blockers / missing items</h3>{_rows(data["blockers"])}</div><div><h3>Intentionally withheld</h3>{_rows(data["withheld"])}</div></div></section>
<section class="panel" aria-labelledby="map-title"><div class="section-heading"><span class="step">06</span><h2 id="map-title">Package map</h2></div><p>{escape(deployment["description"])}</p><p class="small">{escape('Deploy only ' + deployment['path'] + '. Never deploy the package root.' if deployment.get('path') else 'No subtree is cleared for deployment by this package.')}</p><ul class="map">{''.join(map_html)}</ul></section>
<section class="panel" aria-labelledby="verification-title"><div class="section-heading"><span class="step">07</span><h2 id="verification-title">Verification summary</h2></div><div class="verification"><div class="result"><strong>Package checks: Passed on publication</strong><p>Archive integrity, source preservation, guide metadata, and declared local links.</p>{_link('_package/verification.json', 'Read packaging verification')}</div><div class="result"><strong>Project verification: {escape(reported)}</strong><p>{escape(verification['summary'])}</p>{evidence}</div></div></section>
<section class="panel" aria-labelledby="docs-title"><div class="section-heading"><span class="step">08</span><h2 id="docs-title">Documentation links</h2></div><ul class="doc-links">{docs}</ul></section>
</main><footer class="foot"><span>{escape(kind.title())} · {escape(data["version"])}</span><span>Start with this guide. Keep the project files together.</span></footer></div></body></html>
'''.encode("utf-8")


def _markdown(value):
    """Keep caller prose literal when a Markdown viewer opens the quick start."""
    value = escape(value, quote=False).replace("\\", "\\\\")
    return re.sub(r"([`*_[\]()])", r"\\\1", value)


def _readme(data):
    primary = data["primary"]
    verification = data["verification"]
    lines = ["Open `index.html` first.", "", f'# {_markdown(data["project"]["name"])} — {data["artifact_type"].title()} {data["version"]}', "", f'Created: {_markdown(data["created_at"])}', f'Status: {_markdown(data["lifecycle"])}', f'Deployment posture: {data["deployment"]["posture"]}', "", f'Start here: [{_markdown(primary["label"])}](<{_href(primary["path"])}>)', _markdown(primary["description"]), "", "## What changed", _markdown(data["change"]), "", "## Deployment", _markdown(data["deployment"]["description"]), "Deploy only `" + data["deployment"]["path"].replace("`", "&#96;") + "`; never deploy the package root." if data["deployment"].get("path") else "No subtree is cleared for deployment.", "", "## Project verification", f'{verification["status"]} (caller-reported). {_markdown(verification["summary"])}', "", "The original authored tree is preserved under `project/`. Do not split that tree", "or replace its index with this package guide. `artifact-manifest.json` describes", "navigation and review context; it is not a payload checksum inventory.", "", "## Documentation"]
    for doc in data["documentation"]:
        lines.append(f'- [{_markdown(doc["label"])}](<{_href(doc["path"])}>) — {_markdown(doc["description"])}')
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_index(*, project_name, slug, artifact_type, version, change, payload_paths,
                primary, review_targets=(), metadata=None, namespace=None,
                created_at=None, docs=()):
    metadata = _object({} if metadata is None else metadata, METADATA_FIELDS, "package metadata")
    if not isinstance(artifact_type, str) or artifact_type not in {"checkpoint", "handoff"}:
        raise ValueError("artifact_type must be checkpoint or handoff")
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise ValueError("version must be stable SemVer X.Y.Z")
    paths = {_path(path, "payload path") for path in payload_paths}
    if not paths:
        raise ValueError("package has no payload")
    supplied_primary = metadata.get("primary")
    if "primary" in metadata:
        _object(supplied_primary, {"path", "label", "description", "role"}, "primary")
        if primary is not None and primary.get("path") != supplied_primary.get("path"):
            raise ValueError("metadata primary path conflicts with the CLI primary target")
        primary = {**(primary or {}), **supplied_primary}
    if primary is None:
        raise ValueError("a primary target is required (--primary or package metadata primary)")
    normalized_primary = _target(primary, paths, "primary", primary=True)
    merged = {}
    for source, label in ((review_targets, "CLI review targets"), (metadata.get("review_targets", []), "metadata review_targets")):
        seen = set()
        for row in _list(source, label):
            _object(row, {"path", "label", "description", "role"}, label)
            path = row.get("path")
            if not isinstance(path, str) or path in seen:
                raise ValueError(f"duplicate or invalid {label} path")
            seen.add(path)
            merged[path] = {**merged.get(path, {}), **row}
    normalized_reviews = [_target(row, paths, "review target") for row in merged.values()]
    if any(row["path"] == normalized_primary["path"] for row in normalized_reviews):
        raise ValueError("the primary target cannot also be a review target")
    decisions = _strings(metadata.get("decisions", []), "decisions")
    blockers = _strings(metadata.get("blockers", []), "blockers")
    withheld = _strings(metadata.get("withheld", []), "withheld")
    verification_input = _object(metadata.get("verification", {}), {"status", "summary", "evidence"}, "verification")
    status = verification_input.get("status", "not-run")
    if not isinstance(status, str) or status not in {"not-run", "passed", "failed"}:
        raise ValueError("verification.status must be not-run, passed, or failed")
    evidence = verification_input.get("evidence")
    if "evidence" in verification_input:
        evidence = _source_file(evidence, paths, "verification.evidence")
    if status != "not-run" and not evidence:
        raise ValueError("reported passed/failed verification requires an evidence file")
    verification = {"status": status, "source": "caller-reported", "summary": _text(verification_input.get("summary", "No project verification was reported." if status == "not-run" else f"The caller reports project verification {status}."), "verification.summary"), "evidence": "project/" + _source_file(evidence, paths, "verification.evidence") if evidence else None}
    deployment_input = _object(metadata.get("deployment", {}), {"posture", "path", "description"}, "deployment")
    posture = deployment_input.get("posture", "review-only")
    if not isinstance(posture, str) or posture not in {"review-only", "implementation-ready", "deployable"}:
        raise ValueError("invalid deployment.posture")
    if artifact_type == "checkpoint" and posture != "review-only":
        raise ValueError("checkpoints are review-only and cannot authorize implementation or deployment")
    deploy_path = deployment_input.get("path")
    if posture == "deployable":
        deploy_path = _path(deploy_path, "deployment.path", directory=True, allow_root=True)
        if deploy_path != "." and not any(path.startswith(deploy_path + "/") for path in paths):
            raise ValueError("deployment.path must be a real payload directory")
        if decisions or blockers or withheld:
            raise ValueError("deployment cannot be approved with unresolved decisions, blockers, or withheld items")
        if status != "passed" or not evidence:
            raise ValueError("deployment requires reported passed project verification with evidence")
    elif deploy_path is not None:
        raise ValueError("deployment.path is only valid with deployable posture")
    default_description = {"review-only": "Review material only. This package does not authorize deployment.", "implementation-ready": "Accepted for implementation. Deployment requires a separate decision and verification.", "deployable": "The caller explicitly approved the designated subtree for deployment."}[posture]
    deployment = {"posture": posture, "path": ("project/" if deploy_path == "." else "project/" + deploy_path + "/") if deploy_path else None, "description": _text(deployment_input.get("description", default_description), "deployment.description")}
    lifecycle = _text(metadata.get("lifecycle", "In progress" if artifact_type == "checkpoint" else "Accepted" if posture != "review-only" else "Prepared handoff"), "lifecycle")
    docs = _list(docs, "documentation")
    documentation = [{"path": "README.md", "label": "Readme / quick start", "description": "How to open and use this package."}, {"path": "artifact-manifest.json", "label": "Package navigation metadata", "description": "The structured source for this guide."}]
    for row in docs:
        row = _object(row, {"path", "label", "description"}, "documentation")
        path = _path(row.get("path"), "documentation.path")
        documentation.append({"path": path, "label": _text(row.get("label"), "documentation.label"), "description": _text(row.get("description", "Generated package documentation."), "documentation.description")})
    for path in sorted(paths):
        name = PurePosixPath(path).name.lower()
        if name in {"readme.md", "changelog.md", "copy.md", "options.md", "copy-notes.md", "options-notes.md"}:
            documentation.append({"path": "project/" + path, "label": path, "description": "Original project documentation."})
    if len({row["path"] for row in documentation}) != len(documentation):
        raise ValueError("duplicate documentation link")
    expected_names = {"project/" + path for path in paths} | GENERATED_PATHS | {row["path"] for row in docs}
    root_entries = {path.split("/", 1)[0] + ("/" if "/" in path else "") for path in expected_names}
    root_descriptions = {"project/": ("source", "Original authored files, preserved together. See the annotated entries below."), "index.html": ("documentation", "Canonical human entrypoint: open this guide first."), "README.md": ("documentation", "Quick start generated from the same package metadata."), "artifact-manifest.json": ("documentation", "Navigation, review context, decisions, and deployment posture."), "_package/": ("evidence", "Packaging verification report; distinct from project verification."), "_checkpoint/": ("documentation", "Nonfinal checkpoint changelog and review context."), "_handoff/": ("documentation", "Handoff provenance, exhaustive payload manifest, and checksums.")}
    package_map = []
    for path in sorted(root_entries):
        role, description = root_descriptions.get(path, ("documentation", "Generated package documentation."))
        package_map.append({"path": path, "role": role, "description": description})
    overrides = {}
    for row in _list(metadata.get("package_map", []), "package_map"):
        row = _object(row, {"path", "role", "description"}, "package_map entry")
        path = _path(row.get("path"), "package_map.path", directory=True)
        if path not in paths and not any(item.startswith(path + "/") for item in paths):
            raise ValueError(f"package_map path does not exist: {path}")
        if path in overrides:
            raise ValueError(f"duplicate package_map path: {path}")
        role = row.get("role")
        if not isinstance(role, str) or role not in ROLES:
            raise ValueError("invalid package_map.role")
        if role == "deployable" and (posture != "deployable" or (deploy_path != "." and path != deploy_path and not path.startswith(deploy_path + "/"))):
            raise ValueError("deployable package map entries must lie in the approved deployment subtree")
        if role == "review-only" and posture == "deployable" and (deploy_path == "." or path == deploy_path or path.startswith(deploy_path + "/")):
            raise ValueError("review-only package map entries cannot lie in the approved deployment subtree")
        overrides[path] = {"path": "project/" + path + ("" if path in paths else "/"), "role": role, "description": _text(row.get("description"), "package_map.description")}
    source_top = {path.split("/", 1)[0] for path in paths}
    map_paths = source_top | set(overrides)
    if posture == "deployable" and deploy_path != ".":
        map_paths.add(deploy_path)
    for path in sorted(map_paths):
        if path in overrides:
            package_map.append(overrides[path])
        elif posture == "deployable" and path == deploy_path:
            package_map.append({"path": "project/" + path + "/", "role": "deployable", "description": "The caller explicitly approved this subtree for deployment."})
        else:
            package_map.append({"path": "project/" + path + ("" if path in paths else "/"), "role": "source", "description": "Original project content. No more specific purpose was supplied."})
    if posture == "deployable" and deploy_path == ".":
        root_project = next(row for row in package_map if row["path"] == "project/")
        root_project.update(role="deployable", description="The caller explicitly approved this preserved project subtree for deployment.")
    doc_paths = {row["path"] for row in documentation}
    for row in overrides.values():
        if row["role"] in {"documentation", "evidence"} and not row["path"].endswith("/") and row["path"] not in doc_paths:
            documentation.append({"path": row["path"], "label": row["path"].removeprefix("project/"), "description": row["description"]})
            doc_paths.add(row["path"])
    checklist = _strings(metadata.get("review_checklist", [f'Open {normalized_primary["label"]} and inspect the current work.', "Compare the linked alternatives and evidence." if normalized_reviews else "Review the package map and supporting documentation.", "Resolve the decisions below and confirm the deployment posture before use."]), "review_checklist")
    if not checklist:
        raise ValueError("review_checklist must contain at least one step")
    stamp = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(stamp, datetime):
        stamp = stamp.isoformat()
    stamp = _text(stamp, "created_at")
    data = {"schema_version": 1, "project": {"name": _text(project_name, "project_name"), "slug": _text(slug, "slug"), "namespace": _text(namespace, "namespace") if namespace is not None else None}, "artifact_type": artifact_type, "version": version, "created_at": stamp, "lifecycle": lifecycle, "deployment": deployment, "primary": normalized_primary, "review_targets": normalized_reviews, "review_checklist": checklist, "change": _text(change, "change"), "decisions": decisions, "blockers": blockers, "withheld": withheld, "package_map": package_map, "verification": verification, "documentation": documentation}
    report = {"schema_version": 1, "scope": "packaging", "status": "passed-on-publication", "created_at": stamp, "checks": ["Portable archive names and unique entries", "ZIP CRC and preserved source bytes", "Generated guide, navigation metadata, and declared local links", "Package map coverage"], "publication_condition": "Published only after the packaging helper validates the private ZIP. This report does not claim project design tests were run.", "project_verification": verification}
    generated = {"index.html": _html(data), "README.md": _readme(data), "artifact-manifest.json": _json_bytes(data), "_package/verification.json": _json_bytes(report)}
    validate_index(generated, expected_names)
    return generated


class _GuideParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.ids = set()
        self.unsafe = False
        self.in_style = False
        self.styles = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"script", "iframe", "object", "embed", "base", "form", "link"}:
            self.unsafe = True
        if tag == "style":
            self.in_style = True
        if "id" in attributes:
            self.ids.add(attributes["id"])
        for key, value in attrs:
            if key.startswith("on") or key in {"src", "srcset", "action", "formaction"}:
                self.unsafe = True
            if key == "href":
                self.links.append(value)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)


def _existing(path, names):
    return path in names or (path.endswith("/") and any(name.startswith(path) for name in names))


def validate_index(generated, archive_names):
    missing = GENERATED_PATHS - set(generated)
    if missing:
        raise ValueError(f"missing generated guide files: {sorted(missing)}")
    names = set(archive_names)
    if not GENERATED_PATHS <= names:
        raise ValueError("archive is missing canonical package entrypoint files")
    data = json.loads(generated["artifact-manifest.json"].decode("utf-8"))
    if generated["index.html"] != _html(data) or generated["README.md"] != _readme(data):
        raise ValueError("guide HTML/README drift from the package navigation metadata")
    report = json.loads(generated["_package/verification.json"].decode("utf-8"))
    if report.get("project_verification") != data["verification"] or report.get("created_at") != data["created_at"]:
        raise ValueError("packaging verification report drift from navigation metadata")
    parser = _GuideParser()
    parser.feed(generated["index.html"].decode("utf-8"))
    if parser.unsafe or re.search(r"@import|url\s*\(", "".join(parser.styles), re.I):
        raise ValueError("package guide must be self-contained HTML without scripts or external resources")
    for href in parser.links:
        if not isinstance(href, str):
            raise ValueError("empty guide link")
        if href.startswith("#"):
            if href[1:] not in parser.ids:
                raise ValueError(f"guide anchor does not exist: {href}")
            continue
        url = urlsplit(href)
        if url.scheme or url.netloc or url.query or url.fragment:
            raise ValueError(f"guide link must be a relative archive path: {href}")
        path = _path(unquote(url.path), "guide link", directory=href.endswith("/"))
        if href.endswith("/"):
            path += "/"
        if not _existing(path, names):
            raise ValueError(f"guide link does not exist inside archive: {path}")
    declared = [data["primary"]["path"], *(row["path"] for row in data["review_targets"]), *(row["path"] for row in data["documentation"])]
    if data["verification"].get("evidence"):
        declared.append(data["verification"]["evidence"])
    if data["deployment"].get("path"):
        declared.append(data["deployment"]["path"])
    for path in declared:
        if not _existing(path, names):
            raise ValueError(f"declared local link does not exist inside archive: {path}")
    mapped = {row["path"] for row in data["package_map"]}
    roots = {path.split("/", 1)[0] + ("/" if "/" in path else "") for path in names}
    if not roots <= mapped:
        raise ValueError(f"package map omits root entries: {sorted(roots - mapped)}")
    payload_top = {"project/" + path.removeprefix("project/").split("/", 1)[0] + ("/" if "/" in path.removeprefix("project/") else "") for path in names if path.startswith("project/")}
    if not payload_top <= mapped:
        raise ValueError(f"package map omits source entries: {sorted(payload_top - mapped)}")
    for path in mapped:
        if not _existing(path, names):
            raise ValueError(f"package map contains nonexistent entry: {path}")
    if not generated["README.md"].decode("utf-8").startswith("Open `index.html` first.\n"):
        raise ValueError("root README must point to index.html first")
