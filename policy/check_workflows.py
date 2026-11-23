#!/usr/bin/env python3
"""Public-repository safety rules for GitHub Actions workflows and composite actions.

  WF001  third-party actions are pinned to a full commit SHA (local ./ actions are exempt)
  WF002  workflows triggered by pull requests never run on self-hosted runners, except jobs that
         are explicitly limited to same-repository branches (head.repo.full_name == github.repository)
  WF003  `pull_request_target` is not used (it runs fork code with a privileged token)
  WF004  every workflow declares top-level `permissions`
  WF005  `run:` blocks do not expand untrusted values inline (github.event.*, inputs.*, head_ref);
         pass them through `env:` instead (script injection)

Usage: python policy/check_workflows.py [paths...]   (default: .github/workflows, ci-templates)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
UNTRUSTED = re.compile(r"\$\{\{\s*(github\.event\.[^}]*|inputs\.[^}]*|github\.head_ref)\s*\}\}")
SAME_REPO = "github.event.pull_request.head.repo.full_name == github.repository"


def triggers(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))  # PyYAML reads the key `on` as True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def runs_self_hosted(job: dict) -> bool:
    r = job.get("runs-on")
    labels = r if isinstance(r, list) else [r]
    return any("self-hosted" in str(l) for l in labels)


def steps_of(doc: dict) -> list[tuple[str, dict]]:
    out = []
    for jname, job in (doc.get("jobs") or {}).items():
        for st in job.get("steps") or []:
            out.append((jname, st))
    for st in (doc.get("runs") or {}).get("steps") or []:   # composite action
        out.append(("composite", st))
    return out


def check(path: Path, doc: dict) -> list[str]:
    f = []
    name = path.as_posix()
    is_workflow = "jobs" in doc
    trig = triggers(doc) if is_workflow else set()
    if "pull_request_target" in trig:
        f.append(f"WF003 {name}: pull_request_target is not allowed")
    if is_workflow and "permissions" not in doc:
        f.append(f"WF004 {name}: declare top-level permissions")
    if trig & {"pull_request", "pull_request_target"}:
        for jname, job in (doc.get("jobs") or {}).items():
            if runs_self_hosted(job) and SAME_REPO not in str(job.get("if", "")):
                f.append(f"WF002 {name}: job {jname} runs on self-hosted runners for pull requests")
    uses_list = [(j, st.get("uses")) for j, st in steps_of(doc) if st.get("uses")]
    uses_list += [(j, job.get("uses")) for j, job in (doc.get("jobs") or {}).items() if job.get("uses")]
    for jname, uses in uses_list:
        if uses.startswith("./") or uses.startswith("docker://"):
            continue
        if not SHA.match(uses.split(" ")[0]):
            f.append(f"WF001 {name}: {jname} uses {uses!r} without a commit SHA")
    for jname, st in steps_of(doc):
        run = st.get("run")
        if run and UNTRUSTED.search(str(run)):
            f.append(f"WF005 {name}: {jname} step {st.get('name', '?')!r} expands an untrusted value inline in run:")
    return f


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv] or [ROOT / ".github/workflows", ROOT / "ci-templates"]
    files = []
    for p in paths:
        files += sorted(p.rglob("*.yml")) + sorted(p.rglob("*.yaml")) if p.is_dir() else [p]
    findings = []
    checked = 0
    for fp in files:
        doc = yaml.safe_load(fp.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not ("jobs" in doc or "runs" in doc):
            continue   # e.g. the Bitbucket template
        checked += 1
        findings += check(fp.relative_to(ROOT) if fp.is_relative_to(ROOT) else fp, doc)
    for line in findings:
        print(line)
    print(f"{checked} workflow/action files checked, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
