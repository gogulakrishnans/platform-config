"""Tests for policy/check_workflows.py."""
import importlib.util
import sys
from pathlib import Path

import yaml

spec = importlib.util.spec_from_file_location("check_workflows", Path(__file__).parents[1] / "check_workflows.py")
cw = importlib.util.module_from_spec(spec)
sys.modules["check_workflows"] = cw
spec.loader.exec_module(cw)

SHA = "actions/checkout@" + "a" * 40


def wf(text):
    return cw.check(Path("w.yml"), yaml.safe_load(text))


def rules(f):
    return sorted({x.split()[0] for x in f})


def test_safe_pr_workflow():
    assert wf(f"on: [pull_request]\npermissions: {{contents: read}}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: {SHA}\n") == []


def test_unpinned_and_missing_permissions():
    f = wf("on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n")
    assert rules(f) == ["WF001", "WF004"]


def test_self_hosted_on_pull_request():
    base = "on: pull_request\npermissions: {}\njobs:\n  a:\n    runs-on: [self-hosted, linux]\n"
    assert rules(wf(base + "    steps: []\n")) == ["WF002"]
    same_repo = "    if: github.event.pull_request.head.repo.full_name == github.repository\n    steps: []\n"
    assert wf(base + same_repo) == []


def test_pull_request_target_forbidden():
    assert "WF003" in rules(wf("on: pull_request_target\npermissions: {}\njobs: {}\n"))


def test_script_injection():
    f = wf("on: issue_comment\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
           "      - run: echo \"${{ github.event.comment.body }}\"\n")
    assert rules(f) == ["WF005"]
    ok = wf("on: issue_comment\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: echo \"$BODY\"\n        env: { BODY: '${{ github.event.comment.body }}' }\n")
    assert ok == []


def test_repository_workflows_are_clean():
    assert cw.main([]) == 0
