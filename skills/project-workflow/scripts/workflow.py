#!/usr/bin/env python3
"""Maintain a local project assignment ledger; never publish or execute prompts."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import quote, urlsplit

STATES = {"draft", "ready", "running", "blocked", "needs_review", "completed", "superseded", "cancelled"}
TERMINAL = {"completed", "superseded", "cancelled"}
NUMBER = re.compile(r"^(\d+)-.+\.md$")
DEFAULT_PATHS = {"prompts": "implementation/prompts", "runs": "implementation/runs", "evidence": "implementation/evidence", "index": "implementation/prompts/README.md"}


def safe_path(root, value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"invalid relative path: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(p in {".", ".."} for p in pure.parts):
        raise ValueError(f"path escapes project: {value!r}")
    path = root.joinpath(*pure.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"path escapes project through symlink: {value!r}")
    if path == root:
        raise ValueError("path must identify a project child")
    return path


def read_ledger(root):
    data = json.loads(safe_path(root, "workflow.json").read_text())
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("workflow.json must use schema_version 1")
    for key in ("prompts", "reservations", "excluded_files"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"{key} must be a list")
    if not isinstance(data.get("project"), str) or not data["project"].strip():
        raise ValueError("project must be a nonempty name")
    if not isinstance(data.get("paths"), dict) or set(data["paths"]) != set(DEFAULT_PATHS):
        raise ValueError("paths must define prompts, runs, evidence and index")
    for value in data["paths"].values():
        safe_path(root, value)
    if safe_path(root, data["paths"]["index"]).suffix != ".md":
        raise ValueError("index must be a Markdown file, not the ledger or a managed directory")
    if type(data.get("next_ordinal")) is not int or data["next_ordinal"] < 1:
        raise ValueError("next_ordinal must be a positive integer")
    return data


def write_json(path, data):
    temporary = path.with_name(path.name + ".tmp")
    # Do not follow an existing symlink placed at a temporary filename.
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


@contextmanager
def locked(root):
    path = safe_path(root, ".workflow.lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError("local workflow lock exists; verify its owner before removing it") from error
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink()


def numbered_files(root, data):
    directory = safe_path(root, data["paths"]["prompts"])
    found = []
    if directory.exists():
        for path in directory.rglob("*.md"):
            match = NUMBER.match(path.name)
            if match:
                safe_path(root, path.relative_to(root).as_posix())
                found.append((int(match.group(1)), path.relative_to(root).as_posix()))
    return sorted(found)


def markdown(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def index_text(root, data):
    base = safe_path(root, data["paths"]["index"]).parent
    lines = [f"# {markdown(data['project'])}: assignments", "", "Generated from `workflow.json`; edit the ledger, then run `workflow.py render`.", "Prompt completion does not imply project delivery.", "", "| ID | Assignment | Status | Latest attempt | Successor |", "|---|---|---|---|---|"]
    for prompt in sorted(data["prompts"], key=lambda p: p["ordinal"]):
        relative = os.path.relpath(safe_path(root, prompt["path"]), base).replace(os.sep, "/")
        attempt = max((r["attempt"] for r in prompt.get("runs", [])), default=0)
        successor = prompt.get("superseded_by")
        lines.append(f"| {prompt['ordinal']:03d} | [{markdown(prompt['title'])}]({quote(relative, safe='/.-')}) | {prompt['status']} | {attempt or '—'} | {successor if successor is not None else '—'} |")
    lines += ["", f"Next ordinal floor: **{data['next_ordinal']:03d}**. Check current remote reservations before allocating.", ""]
    return "\n".join(lines)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return result


def run_fingerprint(root, run):
    packet = safe_path(root, run["result"]).read_bytes()
    encoded = json.dumps(run, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded + b"\n" + packet).hexdigest()


def inspect(root, data, check_index=True):
    errors, warnings = [], []
    prompts = data["prompts"]
    ids, paths, all_runs, open_gaps = {}, set(), [], []
    measurements = []
    evidence_count = 0
    referenced_paths = set()
    index_path = safe_path(root, data["paths"]["index"]).resolve()
    stale_count = 0
    now = datetime.now(timezone.utc)

    def error(message):
        errors.append(message)

    def require_text(value, label):
        if not isinstance(value, str) or not value.strip():
            error(f"{label}: nonempty text required")
            return False
        return True

    def ref(value, label):
        nonlocal evidence_count
        if not isinstance(value, str) or not value:
            error(f"{label}: evidence/reference required")
            return
        if value.startswith("https://"):
            parsed = urlsplit(value)
            if not parsed.netloc or parsed.username or parsed.password:
                error(f"{label}: invalid HTTPS reference")
            else:
                evidence_count += 1
            return
        try:
            path = safe_path(root, value.split("#", 1)[0])
            referenced_paths.add(path.resolve())
            if not path.is_file():
                error(f"{label}: missing file {value}")
            else:
                evidence_count += 1
        except ValueError as exc:
            error(f"{label}: {exc}")

    def refs(values, label, required=True):
        if not isinstance(values, list) or (required and not values):
            error(f"{label}: nonempty evidence list required")
            return
        for value in values:
            ref(value, label)

    for prompt in prompts:
        if not isinstance(prompt, dict):
            error("prompt must be an object")
            continue
        ordinal = prompt.get("ordinal")
        if type(ordinal) is not int or ordinal < 0:
            error("prompt ordinal must be a nonnegative integer")
            continue
        label = f"prompt {ordinal:03d}"
        if ordinal in ids:
            error(f"duplicate ordinal {ordinal}")
        ids[ordinal] = prompt
        require_text(prompt.get("title"), f"{label} title")
        status = prompt.get("status")
        if status not in STATES:
            error(f"{label}: invalid status {status!r}")
        try:
            path = safe_path(root, prompt.get("path"))
            if prompt["path"] in paths:
                error(f"{label}: duplicate canonical path")
            paths.add(prompt["path"])
            referenced_paths.add(path.resolve())
            if status in {"ready", "running", "needs_review", "completed"} and path.is_file() and "TODO" in path.read_text():
                error(f"{label}: executable prompt still contains TODO placeholders")
            if not path.is_file():
                error(f"{label}: missing canonical prompt file")
            match = NUMBER.match(path.name)
            if not match or int(match.group(1)) != ordinal:
                error(f"{label}: filename ordinal does not match")
            folder = "superseded" if status == "superseded" else "closed" if status in TERMINAL else "open"
            if path.parent != safe_path(root, data["paths"]["prompts"]) / folder:
                error(f"{label}: status requires {folder}/ canonical path")
        except ValueError as exc:
            path = None
            error(f"{label}: {exc}")
        criteria = prompt.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria or not all(isinstance(c, str) and c.strip() for c in criteria) or len(set(criteria)) != len(criteria):
            error(f"{label}: unique nonempty acceptance_criteria IDs required")
            criteria = []
        dependencies = prompt.get("depends_on")
        if not isinstance(dependencies, list) or any(type(d) is not int for d in dependencies):
            error(f"{label}: depends_on must be an integer list")
        for field in ("runs", "reviews", "gaps"):
            if not isinstance(prompt.get(field), list):
                error(f"{label}: {field} must be a list")
        runs = prompt.get("runs") if isinstance(prompt.get("runs"), list) else []
        reviews = prompt.get("reviews") if isinstance(prompt.get("reviews"), list) else []
        gaps = prompt.get("gaps") if isinstance(prompt.get("gaps"), list) else []
        attempts = {}
        for run in runs:
            if not isinstance(run, dict):
                error(f"{label}: run must be an object")
                continue
            attempt = run.get("attempt")
            if type(attempt) is not int or attempt < 1 or attempt in attempts:
                error(f"{label}: duplicate or invalid run attempt")
                continue
            attempts[attempt] = run
            all_runs.append(run)
            rl = f"{label} attempt {attempt}"
            require_text(run.get("executor"), f"{rl} executor")
            if not re.fullmatch(r"[0-9a-f]{40}", str(run.get("source_revision", ""))):
                error(f"{rl}: source_revision must be a full commit SHA")
            digest = run.get("prompt_sha256")
            if not re.fullmatch(r"[0-9a-f]{64}", str(digest or "")):
                error(f"{rl}: prompt_sha256 required")
            elif path and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                error(f"{rl}: executed instructions hash mismatch")
            ref(run.get("result"), f"{rl} result")
            try:
                timestamp(run.get("recorded_at"))
            except (ValueError, TypeError):
                error(f"{rl}: recorded_at must be an ISO timestamp with timezone")
            results = run.get("criteria")
            seen = set()
            if not isinstance(results, list):
                error(f"{rl}: criteria results must be a list")
                results = []
            for criterion in results:
                if not isinstance(criterion, dict):
                    error(f"{rl}: criterion result must be an object")
                    continue
                cid = criterion.get("id")
                if not isinstance(cid, str) or cid in seen or cid not in criteria:
                    error(f"{rl}: unknown or duplicate criterion ID")
                if isinstance(cid, str):
                    seen.add(cid)
                if criterion.get("status") not in {"met", "unmet", "untested"}:
                    error(f"{rl}: criterion status must be met, unmet or untested")
                refs(criterion.get("evidence"), f"{rl} {cid}", criterion.get("status") == "met")
            if set(criteria) != seen:
                error(f"{rl}: result must account for every acceptance criterion")
            validations = run.get("validations")
            if not isinstance(validations, list) or not validations:
                error(f"{rl}: validations required (record blocked checks explicitly)")
                validations = []
            for validation in validations:
                if not isinstance(validation, dict):
                    error(f"{rl}: validation must be an object")
                    continue
                require_text(validation.get("command"), f"{rl} validation command")
                if validation.get("outcome") not in {"pass", "fail", "blocked"}:
                    error(f"{rl}: validation outcome must be pass, fail or blocked")
                refs(validation.get("evidence"), f"{rl} validation evidence")
            refs(run.get("artifacts"), f"{rl} artifacts", required=False)
            measure = run.get("measurement")
            if measure is not None:
                keys = {"handoff_minutes", "status_corrections", "repeated_discovery_minutes", "bookkeeping_minutes"}
                if not isinstance(measure, dict) or set(measure) != keys or any(type(v) not in (int, float) or v < 0 for v in measure.values()):
                    error(f"{rl}: measurement requires four nonnegative numeric values")
                else:
                    measurements.append(measure)
        if status in {"needs_review", "completed"} and not runs:
            error(f"{label}: status requires a recorded run")
        if attempts and sorted(attempts) != list(range(1, max(attempts) + 1)):
            error(f"{label}: run attempts must be consecutive from 1")
        latest_reviews = {}
        for review in reviews:
            if not isinstance(review, dict):
                error(f"{label}: review must be an object")
                continue
            attempt = review.get("attempt")
            if type(attempt) is not int or attempt not in attempts:
                error(f"{label}: review references missing attempt")
                continue
            rl = f"{label} review of attempt {attempt}"
            require_text(review.get("reviewer"), f"{rl} reviewer")
            if review.get("reviewer") == attempts[attempt].get("executor"):
                error(f"{rl}: review must be independent of executor")
            if review.get("decision") not in {"accepted", "changes_requested"}:
                error(f"{rl}: invalid review decision")
            try:
                if review.get("run_sha256") != run_fingerprint(root, attempts[attempt]):
                    error(f"{rl}: run_sha256 mismatch; result or run record changed after review")
            except (OSError, ValueError, KeyError, TypeError):
                error(f"{rl}: cannot fingerprint missing or invalid run result")
            try:
                at = timestamp(review.get("recorded_at"))
                if at < timestamp(attempts[attempt].get("recorded_at")):
                    error(f"{rl}: review predates its run")
                if attempt not in latest_reviews or at >= latest_reviews[attempt][0]:
                    latest_reviews[attempt] = (at, review)
            except (ValueError, TypeError):
                error(f"{rl}: recorded_at must be an ISO timestamp with timezone")
            ref(review.get("result"), f"{rl} result")
            refs(review.get("evidence"), f"{rl} evidence")
        if status == "completed" and attempts:
            latest = max(attempts)
            decision = latest_reviews.get(latest, (None, {}))[1].get("decision")
            if decision != "accepted":
                error(f"{label}: completed requires accepted independent review of latest attempt")
            if any(c.get("status") != "met" for c in attempts[latest].get("criteria", []) if isinstance(c, dict)):
                error(f"{label}: completed requires all acceptance criteria met")
        if status in {"superseded", "cancelled"}:
            require_text(prompt.get("reason"), f"{label} closeout reason")
        if status == "superseded":
            if type(prompt.get("superseded_by")) is not int:
                error(f"{label}: superseded requires successor ordinal")
        elif prompt.get("superseded_by") is not None:
            error(f"{label}: successor only valid for superseded prompt")
        gap_ids = set()
        for gap in gaps:
            if not isinstance(gap, dict):
                error(f"{label}: gap must be an object")
                continue
            gid = gap.get("id")
            if not isinstance(gid, str) or not gid or gid in gap_ids:
                error(f"{label}: unique gap IDs required")
            if isinstance(gid, str):
                gap_ids.add(gid)
            require_text(gap.get("summary"), f"{label} gap summary")
            if gap.get("status") not in {"open", "resolved"}:
                error(f"{label}: gap status must be open or resolved")
            if gap.get("status") == "open":
                open_gaps.append(gap)
                require_text(gap.get("owner"), f"{label} open gap owner")
                destination = gap.get("destination")
                if isinstance(destination, str) and re.fullmatch(r"prompt:\d+", destination):
                    pass  # Validate after all IDs are known.
                else:
                    ref(destination, f"{label} open gap destination")
            else:
                refs(gap.get("evidence"), f"{label} resolved gap evidence")
        if status not in TERMINAL and prompt.get("updated_at"):
            try:
                if (now - timestamp(prompt["updated_at"])).days >= 14:
                    stale_count += 1
                    warnings.append(f"{label}: no recorded status update for 14 days")
            except (ValueError, TypeError):
                error(f"{label}: invalid updated_at timestamp")
    for ordinal, prompt in ids.items():
        dependencies = prompt.get("depends_on", [])
        if isinstance(dependencies, list):
            for dep in dependencies:
                if type(dep) is not int or dep not in ids or dep == ordinal:
                    error(f"prompt {ordinal:03d}: invalid dependency {dep!r}")
        successor = prompt.get("superseded_by")
        if successor is not None and (type(successor) is not int or successor not in ids or successor <= ordinal):
            error(f"prompt {ordinal:03d}: successor must be an existing later ordinal")
    # Graph traversal also catches cycles in a chain of otherwise valid dependencies.
    def cycle(node, visiting, visited):
        if node in visiting:
            return True
        if node in visited or node not in ids:
            return False
        visiting.add(node)
        children = ids[node].get("depends_on", [])
        if isinstance(children, list):
            for child in children:
                if type(child) is int and cycle(child, visiting, visited):
                    return True
        visiting.remove(node)
        visited.add(node)
        return False
    if any(cycle(n, set(), set()) for n in ids):
        error("dependency cycle detected")
    for gap in open_gaps:
        dest = gap.get("destination")
        if isinstance(dest, str) and re.fullmatch(r"prompt:\d+", dest):
            target = int(dest.split(":")[1])
            if target not in ids or ids[target].get("status") in TERMINAL:
                error(f"open gap {gap.get('id')}: destination prompt must exist and remain active")
    reservations = []
    for item in data["reservations"]:
        if not isinstance(item, dict) or type(item.get("ordinal")) is not int or item["ordinal"] < 0:
            error("reservation must include a nonnegative integer ordinal")
            continue
        require_text(item.get("source"), "reservation source")
        reservations.append(item["ordinal"])
        if item["ordinal"] in ids:
            error(f"ordinal {item['ordinal']} conflicts with a reservation")
    if len(reservations) != len(set(reservations)):
        error("duplicate reserved ordinal")
    excluded = {}
    for item in data["excluded_files"]:
        if not isinstance(item, dict):
            error("excluded file must have path and reason")
            continue
        try:
            safe_path(root, item.get("path"))
            require_text(item.get("reason"), "excluded file reason")
            excluded[item["path"]] = item["reason"]
        except ValueError as exc:
            error(str(exc))
    try:
        numbered = numbered_files(root, data)
        for ordinal, file in numbered:
            if file not in paths and file not in excluded:
                error(f"unregistered numbered prompt: {file}")
        for file in excluded:
            if file in paths:
                error(f"canonical prompt cannot be excluded: {file}")
            elif not safe_path(root, file).is_file():
                error(f"excluded file missing: {file}")
        if excluded:
            warnings.append(f"{len(excluded)} legacy/redirect files excluded from lifecycle validation; ordinals still reserved")
        high = max([0, *ids, *reservations, *(n for n, _ in numbered)])
        if data["next_ordinal"] <= high:
            error("next_ordinal must exceed all registered, reserved and legacy ordinals")
    except ValueError as exc:
        error(str(exc))
    if index_path in referenced_paths or index_path == safe_path(root, "workflow.json").resolve():
        error("generated index path must not overwrite a prompt, result, evidence file or ledger")
    if any(index_path == safe_path(root, data["paths"][key]).resolve() for key in ("prompts", "runs", "evidence")):
        error("generated index path must not be a managed directory")
    if check_index and not errors:
        target = safe_path(root, data["paths"]["index"])
        if not target.is_file() or target.read_text() != index_text(root, data):
            error("generated index is stale; run render")
    if evidence_count:
        warnings.append("Reference existence was checked locally; external links and evidence meaning require independent review")
    metrics = {"prompt_count": len(prompts), "run_count": len(all_runs), "completed_count": sum(p.get("status") == "completed" for p in prompts if isinstance(p, dict)), "needs_review_count": sum(p.get("status") == "needs_review" for p in prompts if isinstance(p, dict)), "open_gap_count": len(open_gaps), "unowned_gap_count": sum(not g.get("owner") or not g.get("destination") for g in open_gaps), "stale_active_count": stale_count, "measured_run_count": len(measurements), "unmeasured_run_count": len(all_runs) - len(measurements)}
    metrics["measurement_averages"] = {key: round(sum(m[key] for m in measurements) / len(measurements), 2) for key in measurements[0]} if measurements else None
    fingerprints = {}
    for ordinal, prompt in ids.items():
        for run in prompt.get("runs", []) if isinstance(prompt.get("runs"), list) else []:
            try:
                fingerprints[f"{ordinal:03d}/" + str(run["attempt"])] = run_fingerprint(root, run)
            except (OSError, ValueError, KeyError, TypeError):
                pass
    return {"errors": errors, "warnings": warnings, "metrics": metrics, "run_fingerprints": fingerprints}


def render(root, data):
    findings = inspect(root, data, check_index=False)
    if findings["errors"]:
        raise ValueError("cannot render invalid ledger:\n" + "\n".join(findings["errors"]))
    target = safe_path(root, data["paths"]["index"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(index_text(root, data), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "new", "check", "render", "report"))
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--name")
    parser.add_argument("--index", default=DEFAULT_PATHS["index"])
    parser.add_argument("--title")
    parser.add_argument("--slug")
    parser.add_argument("--reserved-ordinal", action="append", default=[], type=int)
    parser.add_argument("--reservation-source")
    args = parser.parse_args(argv)
    root = args.project_dir.expanduser().resolve()
    try:
        if args.command == "init":
            if not args.name or not args.name.strip():
                raise ValueError("init requires --name")
            root.mkdir(parents=True, exist_ok=True)
            with locked(root):
                ledger = safe_path(root, "workflow.json")
                target = safe_path(root, args.index)
                if target.suffix != ".md" or target.resolve() == ledger.resolve():
                    raise ValueError("index must be a Markdown file and must not overwrite the ledger")
                if ledger.exists() or target.exists():
                    raise ValueError("refusing to overwrite an existing ledger or index; import deliberately or choose --index")
                data = {"schema_version": 1, "project": args.name, "next_ordinal": 1, "paths": dict(DEFAULT_PATHS, index=args.index), "prompts": [], "reservations": [], "excluded_files": []}
                for key in ("prompts", "runs", "evidence"):
                    safe_path(root, data["paths"][key]).mkdir(parents=True, exist_ok=True)
                data["next_ordinal"] = max([0, *(n for n, _ in numbered_files(root, data))]) + 1
                write_json(ledger, data)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(index_text(root, data), encoding="utf-8")
                print(f"Created {ledger}; import any existing numbered prompts before check can pass")
            return 0
        if args.command == "new":
            if not args.title or not args.title.strip() or not args.slug or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug):
                raise ValueError("new requires --title and a lowercase kebab-case --slug")
            if args.reserved_ordinal and (not args.reservation_source or any(n < 0 for n in args.reserved_ordinal)):
                raise ValueError("nonnegative reserved ordinals require --reservation-source")
            with locked(root):
                data = read_ledger(root)
                existing = inspect(root, data, check_index=False)
                # An imported project's unregistered files can still reserve numbers.
                fatal = [e for e in existing["errors"] if not e.startswith(("unregistered numbered prompt:", "next_ordinal must exceed"))]
                if fatal:
                    raise ValueError("cannot allocate from invalid ledger:\n" + "\n".join(fatal))
                known_reservations = {r["ordinal"] for r in data["reservations"]}
                ids = {p["ordinal"] for p in data["prompts"]}
                if ids.intersection(args.reserved_ordinal):
                    raise ValueError("pending reservation conflicts with a registered prompt")
                for ordinal in sorted(set(args.reserved_ordinal) - known_reservations):
                    data["reservations"].append({"ordinal": ordinal, "source": args.reservation_source})
                high = max([0, *ids, *(r["ordinal"] for r in data["reservations"]), *(n for n, _ in numbered_files(root, data))])
                ordinal = max(high + 1, data["next_ordinal"])
                relative = f"{data['paths']['prompts']}/open/{ordinal:03d}-{args.slug}.md"
                target = safe_path(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                template = (Path(__file__).resolve().parents[1] / "references" / "prompt-template.md").read_text()
                content = template.replace("{{ID}}", f"{ordinal:03d}").replace("{{TITLE}}", args.title)
                with target.open("x", encoding="utf-8") as stream:
                    stream.write(content)
                data["prompts"].append({"ordinal": ordinal, "title": args.title, "path": relative, "status": "draft", "updated_at": datetime.now(timezone.utc).isoformat(), "depends_on": [], "acceptance_criteria": ["AC-1"], "runs": [], "reviews": [], "gaps": [], "superseded_by": None})
                data["next_ordinal"] = ordinal + 1
                write_json(safe_path(root, "workflow.json"), data)
                safe_path(root, data["paths"]["index"]).write_text(index_text(root, data), encoding="utf-8")
                print(f"Created {relative}; local reservation only, recheck remote branches and open PRs before publication")
            return 0
        data = read_ledger(root)
        if args.command == "render":
            with locked(root):
                render(root, read_ledger(root))
            print(data["paths"]["index"])
            return 0
        findings = inspect(root, data)
        if args.command == "report":
            print(json.dumps(findings, indent=2))
        else:
            for entry in findings["errors"]:
                print("ERROR: " + entry)
            for entry in findings["warnings"]:
                print("WARNING: " + entry)
            print(f"Checked {findings['metrics']['prompt_count']} prompt(s); {len(findings['errors'])} error(s)")
        return int(bool(findings["errors"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
