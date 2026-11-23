#!/usr/bin/env python3
"""Static policy checks on rendered Kubernetes manifests (the Helm half of the CI policy gate).

Rules
  K8S-LBL001  Namespaces, workloads and pod templates carry the six mandatory labels with valid
              values (decisions #9; the same rule is enforced at admission by the platform add-on).
  K8S-NS001   Tenant namespaces enforce the "restricted" Pod Security Standard.
  K8S-PSS001  Pods meet the "restricted" Pod Security Standard: no host namespaces, ports or
              hostPath volumes; non-root; no privilege escalation; ALL capabilities dropped;
              RuntimeDefault seccomp; not privileged.
  K8S-RES001  Every container sets CPU and memory requests and a memory limit.
  K8S-IMG001  Images are pinned to a version tag or a digest (never :latest or untagged).
  K8S-IMG002  Prod product workloads (environment=prod, customer != shared) use the promoted
              digest, which Binary Authorization verifies.

Usage: python policy/check_manifests.py <rendered.yaml>...      exit 1 on findings
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

MANDATORY = ("customer", "environment", "env-group", "product", "region-role", "managed-by")
VALUE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
ALLOWED = {
    "environment": {"dev", "stage", "uat", "prod", "shared"},
    "env-group": {"devstage", "uat", "prod", "shared"},
    "region-role": {"primary", "dr"},
    "managed-by": {"terraform", "argocd"},
}
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "Rollout"}
# Istio replaces "auto" with the managed gateway proxy image at injection time.
INJECTED_IMAGES = {"auto"}


def labels_findings(where: str, labels: dict | None) -> list[str]:
    labels = labels or {}
    out = []
    missing = [k for k in MANDATORY if k not in labels]
    if missing:
        out.append(f"K8S-LBL001 {where}: missing labels {missing}")
    for k in MANDATORY:
        v = labels.get(k)
        if v is None:
            continue
        if not VALUE.match(str(v)):
            out.append(f"K8S-LBL001 {where}: label {k}={v!r} is not a valid GCP label value")
        elif k in ALLOWED and v not in ALLOWED[k]:
            out.append(f"K8S-LBL001 {where}: label {k}={v!r} not in {sorted(ALLOWED[k])}")
    return out


def pod_spec(obj: dict) -> tuple[dict, dict] | None:
    """(pod template metadata, pod spec) of a workload, or of a bare Pod."""
    if obj.get("kind") == "Pod":
        return obj.get("metadata", {}), obj.get("spec", {})
    spec = obj.get("spec", {})
    if obj.get("kind") == "CronJob":
        spec = spec.get("jobTemplate", {}).get("spec", {})
    tpl = spec.get("template")
    if obj.get("kind") in WORKLOADS | {"CronJob"} and tpl:
        return tpl.get("metadata", {}), tpl.get("spec", {})
    return None


def pss_findings(where: str, spec: dict) -> list[str]:
    out = []
    for f in ("hostNetwork", "hostPID", "hostIPC"):
        if spec.get(f):
            out.append(f"K8S-PSS001 {where}: {f} is not allowed")
    for v in spec.get("volumes", []) or []:
        if "hostPath" in v:
            out.append(f"K8S-PSS001 {where}: hostPath volume {v.get('name')!r} is not allowed")
    psc = spec.get("securityContext", {}) or {}
    pod_seccomp = (psc.get("seccompProfile") or {}).get("type")
    containers = [("initContainer", c) for c in spec.get("initContainers", []) or []] + \
                 [("container", c) for c in spec.get("containers", []) or []]
    for kind, c in containers:
        cw = f"{where} {kind} {c.get('name')!r}"
        sc = c.get("securityContext", {}) or {}
        if sc.get("privileged"):
            out.append(f"K8S-PSS001 {cw}: privileged")
        if sc.get("allowPrivilegeEscalation") is not False:
            out.append(f"K8S-PSS001 {cw}: allowPrivilegeEscalation must be false")
        caps = sc.get("capabilities", {}) or {}
        if "ALL" not in (caps.get("drop") or []):
            out.append(f"K8S-PSS001 {cw}: capabilities must drop ALL")
        if set(caps.get("add") or []) - {"NET_BIND_SERVICE"}:
            out.append(f"K8S-PSS001 {cw}: only NET_BIND_SERVICE may be added")
        if not (sc.get("runAsNonRoot") or psc.get("runAsNonRoot")):
            out.append(f"K8S-PSS001 {cw}: runAsNonRoot must be true")
        if sc.get("runAsUser", psc.get("runAsUser")) == 0:
            out.append(f"K8S-PSS001 {cw}: runAsUser 0")
        seccomp = (sc.get("seccompProfile") or {}).get("type") or pod_seccomp
        if seccomp not in ("RuntimeDefault", "Localhost"):
            out.append(f"K8S-PSS001 {cw}: seccompProfile must be RuntimeDefault or Localhost")
        for p in c.get("ports", []) or []:
            if p.get("hostPort"):
                out.append(f"K8S-PSS001 {cw}: hostPort {p['hostPort']}")
    return out


def resource_findings(where: str, spec: dict) -> list[str]:
    out = []
    for c in (spec.get("initContainers") or []) + (spec.get("containers") or []):
        res = c.get("resources", {}) or {}
        req, lim = res.get("requests", {}) or {}, res.get("limits", {}) or {}
        if not ("cpu" in req and "memory" in req and "memory" in lim):
            out.append(f"K8S-RES001 {where} container {c.get('name')!r}: needs cpu+memory requests and a memory limit")
    return out


def image_findings(where: str, spec: dict) -> list[str]:
    out = []
    for c in (spec.get("initContainers") or []) + (spec.get("containers") or []):
        img = str(c.get("image", ""))
        if img in INJECTED_IMAGES:
            continue
        name = img.rsplit("/", 1)[-1]
        if "@sha256:" in img:
            continue
        if ":" not in name or name.endswith(":latest"):
            out.append(f"K8S-IMG001 {where} container {c.get('name')!r}: image {img!r} is not pinned")
    return out


def check(objs: list[dict], source: str = "") -> list[str]:
    findings = []
    for o in objs:
        kind = o.get("kind", "?")
        meta = o.get("metadata", {}) or {}
        where = f"{source}{kind}/{meta.get('namespace', '-')}/{meta.get('name', '?')}"
        if kind == "Namespace":
            labels = meta.get("labels", {}) or {}
            findings += labels_findings(where, labels)
            if labels.get("customer") not in (None, "shared") and labels.get("pod-security.kubernetes.io/enforce") != "restricted":
                findings.append(f"K8S-NS001 {where}: tenant namespace must enforce the restricted Pod Security Standard")
        if kind in WORKLOADS | {"CronJob", "Pod"}:
            findings += labels_findings(where, meta.get("labels"))
        ps = pod_spec(o)
        if ps:
            tmeta, spec = ps
            if kind != "Pod":
                findings += labels_findings(where + " (pod template)", tmeta.get("labels"))
            findings += pss_findings(where, spec)
            findings += resource_findings(where, spec)
            findings += image_findings(where, spec)
            labels = meta.get("labels") or {}
            if labels.get("environment") == "prod" and labels.get("customer") not in (None, "shared"):
                for c in spec.get("containers") or []:
                    if "@sha256:" not in str(c.get("image", "")):
                        findings.append(f"K8S-IMG002 {where} container {c.get('name')!r}: prod images must be referenced by digest")
    return findings


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    findings = []
    count = 0
    for f in argv:
        objs = [d for d in yaml.safe_load_all(Path(f).read_text(encoding="utf-8")) if d]
        count += len(objs)
        findings += check(objs, f"{Path(f).name}: ")
    for line in findings:
        print(line)
    print(f"{len(findings)} finding(s) in {count} objects from {len(argv)} file(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
