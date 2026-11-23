"""Tests for policy/check_manifests.py."""
import copy
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_manifests", Path(__file__).parents[1] / "check_manifests.py")
cm = importlib.util.module_from_spec(spec)
sys.modules["check_manifests"] = cm
spec.loader.exec_module(cm)

LABELS = {
    "customer": "acme-corp", "environment": "uat", "env-group": "uat",
    "product": "payment", "region-role": "primary", "managed-by": "argocd",
}
SECURE = {
    "allowPrivilegeEscalation": False, "runAsNonRoot": True, "readOnlyRootFilesystem": True,
    "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"},
}
RES = {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "128Mi"}}


def workload(**container_overrides):
    c = {"name": "app", "image": "r.example/app:1.2.3", "securityContext": copy.deepcopy(SECURE), "resources": RES}
    c.update(container_overrides)
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Rollout",
        "metadata": {"name": "payment", "namespace": "acme-corp-prod", "labels": dict(LABELS)},
        "spec": {"template": {"metadata": {"labels": dict(LABELS)}, "spec": {"containers": [c]}}},
    }


def rules(findings):
    return sorted({f.split()[0] for f in findings})


def test_compliant_workload_passes():
    assert cm.check([workload()]) == []


def test_prod_requires_digest():
    def prod(w):
        for lbl in (w["metadata"]["labels"], w["spec"]["template"]["metadata"]["labels"]):
            lbl.update({"environment": "prod", "env-group": "prod"})
        return w
    assert rules(cm.check([prod(workload())])) == ["K8S-IMG002"]
    assert cm.check([prod(workload(image="r.example/app:1.2.3@sha256:" + "b" * 64))]) == []


def test_missing_label_on_workload_and_template():
    w = workload()
    del w["metadata"]["labels"]["product"]
    del w["spec"]["template"]["metadata"]["labels"]["managed-by"]
    f = cm.check([w])
    assert rules(f) == ["K8S-LBL001"] and len(f) == 2


def test_invalid_label_value():
    w = workload()
    w["metadata"]["labels"]["region-role"] = "secondary"
    w["metadata"]["labels"]["customer"] = "Acme"
    assert len(cm.check([w])) == 2


def test_privilege_escalation_and_caps():
    sc = copy.deepcopy(SECURE)
    sc["allowPrivilegeEscalation"] = True
    sc["capabilities"] = {"drop": ["NET_RAW"], "add": ["SYS_ADMIN"]}
    f = cm.check([workload(securityContext=sc)])
    assert rules(f) == ["K8S-PSS001"] and len(f) == 3


def test_root_and_seccomp_from_pod_level():
    w = workload(securityContext={"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}})
    assert rules(cm.check([w])) == ["K8S-PSS001"]  # neither runAsNonRoot nor seccomp anywhere
    w["spec"]["template"]["spec"]["securityContext"] = {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}}
    assert cm.check([w]) == []


def test_host_namespaces_and_hostpath():
    w = workload()
    w["spec"]["template"]["spec"].update({"hostNetwork": True, "volumes": [{"name": "h", "hostPath": {"path": "/"}}]})
    assert len(cm.check([w])) == 2


def test_resources_required():
    f = cm.check([workload(resources={"requests": {"cpu": "1"}})])
    assert rules(f) == ["K8S-RES001"]


def test_unpinned_images():
    assert rules(cm.check([workload(image="r.example/app")])) == ["K8S-IMG001"]
    assert rules(cm.check([workload(image="r.example/app:latest")])) == ["K8S-IMG001"]
    assert cm.check([workload(image="r.example:5000/app@sha256:" + "a" * 64)]) == []
    assert cm.check([workload(image="auto")]) == []


def test_tenant_namespace_needs_restricted_pss():
    ns = {"kind": "Namespace", "metadata": {"name": "acme-corp-prod", "labels": dict(LABELS)}}
    assert rules(cm.check([ns])) == ["K8S-NS001"]
    ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] = "restricted"
    assert cm.check([ns]) == []


def test_init_containers_are_checked():
    w = workload()
    w["spec"]["template"]["spec"]["initContainers"] = [{"name": "proxy", "image": "r.example/p:2.0.0", "restartPolicy": "Always"}]
    assert set(rules(cm.check([w]))) == {"K8S-PSS001", "K8S-RES001"}
