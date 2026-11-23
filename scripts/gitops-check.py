#!/usr/bin/env python3
"""Offline gate for D4: Helm charts and ArgoCD ApplicationSets, end to end for the example customers.

Steps:
  1. render-gitops --check        the GitOps index matches the registry
  2. helm lint                    every chart, with every generated values file it is used with
  3. root chart                   `helm template argocd/root` per instance (devstage, uat, prod)
  4. ApplicationSets              expand the git-files and cluster generators exactly as ArgoCD does
                                  (goTemplate, missingkey=error) into Application manifests
  5. Applications                 `helm template` each in-repo source with its valueFiles, in order,
                                  honouring ignoreMissingValueFiles
  6. schema validation            kubeconform -strict (Kubernetes + CRD catalog schemas)
  7. policy                       policy/check_manifests.py (labels, Pod Security "restricted", resources)

The expanded Applications and rendered manifests are written to examples/rendered/ so reviewers can
read the output without running anything; --check fails if that snapshot is stale.

Usage:
    python scripts/gitops-check.py                 # run the gate, refresh examples/rendered/
    python scripts/gitops-check.py --check         # run the gate, fail if examples/rendered/ is stale
    python scripts/gitops-check.py --offline       # skip kubeconform (no schema download)
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GROUPS = ("devstage", "uat", "prod")
SNAPSHOT = Path("examples") / "rendered"
K8S_VERSION = "1.33.0"
CRD_SCHEMAS = "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
# Kinds without a public schema; validated by their controllers' admission webhooks instead.
SKIP_KINDS = ""

FAIL: list[str] = []


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", **kw)


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        FAIL.append(name)
        if detail:
            print("     " + detail.strip().replace("\n", "\n     "))


def docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def dump(objs: list[dict]) -> str:
    return "".join("---\n" + yaml.safe_dump(o, sort_keys=False) for o in objs)


# ------------------------------------------------------------------- goTemplate (ArgoCD subset)

ACTION = re.compile(r"\{\{-?\s*(.*?)\s*-?\}\}")
PATH = re.compile(r"^\.([A-Za-z0-9_.]+)$")
INDEX = re.compile(r'^index\s+\.([A-Za-z0-9_.]+)\s+"([^"]+)"$')


class TemplateError(Exception):
    pass


def lookup(params: dict, dotted: str):
    cur = params
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise TemplateError(f"missing key .{dotted}")  # missingkey=error
        cur = cur[part]
    return cur


def render_string(s: str, params: dict) -> str:
    def sub(m: re.Match) -> str:
        expr = m.group(1)
        if p := PATH.match(expr):
            return str(lookup(params, p.group(1)))
        if i := INDEX.match(expr):
            container = lookup(params, i.group(1))
            if i.group(2) not in container:
                raise TemplateError(f"missing key {i.group(2)!r} in .{i.group(1)}")
            return str(container[i.group(2)])
        raise TemplateError(f"unsupported template action {{{{ {expr} }}}}: extend the emulator first")

    return ACTION.sub(sub, s)


def render_template(obj, params: dict):
    """ArgoCD goTemplate renders every string field of the Application template."""
    if isinstance(obj, dict):
        return {render_string(k, params): render_template(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render_template(v, params) for v in obj]
    if isinstance(obj, str):
        return render_string(obj, params)
    return obj


# ------------------------------------------------------------------- generators

def git_files(gen: dict) -> list[dict]:
    out = []
    for f in gen["git"]["files"]:
        for path in sorted(ROOT.glob(f["path"])):
            rel = path.relative_to(ROOT)
            params = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            params["path"] = {
                "path": rel.parent.as_posix(),
                "basename": rel.parent.name,
                "filename": rel.name,
                "basenameNormalized": re.sub(r"[^a-z0-9-]", "-", rel.parent.name.lower()),
                "filenameNormalized": re.sub(r"[^a-z0-9-]", "-", rel.name.lower()),
                "segments": list(rel.parent.parts),
            }
            out.append(params)
    return out


def clusters(gen: dict, secrets: list[dict]) -> list[dict]:
    want = gen["clusters"].get("selector", {}).get("matchLabels", {})
    out = []
    for s in secrets:
        labels = s["metadata"].get("labels", {})
        if all(labels.get(k) == v for k, v in want.items()):
            data = s["stringData"]
            out.append({
                "name": data["name"],
                "nameNormalized": re.sub(r"[^a-z0-9-]", "-", data["name"].lower()),
                "server": data["server"],
                "metadata": {"labels": labels, "annotations": s["metadata"].get("annotations", {})},
            })
    return out


def expand(appset: dict, secrets: list[dict]) -> list[dict]:
    spec = appset["spec"]
    if not spec.get("goTemplate") or "missingkey=error" not in spec.get("goTemplateOptions", []):
        raise TemplateError(f"{appset['metadata']['name']}: goTemplate with missingkey=error is required")
    apps = []
    for gen in spec["generators"]:
        if "git" in gen:
            params = git_files(gen)
        elif "clusters" in gen:
            params = clusters(gen, secrets)
        else:
            raise TemplateError(f"unsupported generator {list(gen)}")
        for p in params:
            body = render_template(spec["template"], p)
            app = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application"}
            app["metadata"] = {**body["metadata"], "namespace": appset["metadata"]["namespace"]}
            app["spec"] = body["spec"]
            apps.append(app)
    names = [a["metadata"]["name"] for a in apps]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise TemplateError(f"{appset['metadata']['name']}: duplicate Application names {dupes}")
    return apps


# ------------------------------------------------------------------- helm

def helm_template(chart: str, release: str, namespace: str, value_files: list[Path], extra: list[str] | None = None) -> str:
    cmd = ["helm", "template", release, chart, "--namespace", namespace]
    for v in value_files:
        cmd += ["-f", str(v)]
    cmd += extra or []
    r = run(cmd)
    if r.returncode:
        raise RuntimeError(f"helm template {chart} ({release}): {r.stderr.strip()}")
    return r.stdout


def app_value_files(app: dict) -> list[Path]:
    src = app["spec"]["source"]
    helm = src.get("helm", {})
    base = ROOT / src["path"]
    files = []
    for vf in helm.get("valueFiles", []):
        p = (base / vf).resolve()
        if ROOT.resolve() not in p.parents:
            raise RuntimeError(f"{app['metadata']['name']}: value file {vf} escapes the repository")
        if not p.exists():
            if helm.get("ignoreMissingValueFiles"):
                continue
            raise RuntimeError(f"{app['metadata']['name']}: value file {vf} not found")
        files.append(p)
    return files


def render_app(app: dict) -> str | None:
    """Render an Application's in-repo source. Remote charts are pinned and rendered by ArgoCD."""
    src = app["spec"]["source"]
    if "chart" in src:
        return None
    helm = src.get("helm", {})
    extra = []
    for p in helm.get("parameters", []):
        extra += ["--set-string", f"{p['name']}={p['value']}"]
    with tempfile.TemporaryDirectory() as tmp:
        files = app_value_files(app)
        if "valuesObject" in helm:
            vo = Path(tmp) / "values-object.yaml"
            vo.write_text(yaml.safe_dump(helm["valuesObject"]), encoding="utf-8")
            files.append(vo)
        return helm_template(src["path"], helm.get("releaseName", app["metadata"]["name"]),
                             app["spec"]["destination"]["namespace"], files, extra)


# ------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if examples/rendered/ is stale")
    ap.add_argument("--offline", action="store_true", help="skip kubeconform")
    args = ap.parse_args(argv)

    r = run([sys.executable, "scripts/render-gitops.py", "--check"])
    step("render-gitops --check (GitOps index in sync with the registry)", r.returncode == 0, r.stdout + r.stderr)

    # helm lint: each chart with every values set it is deployed with
    lint_sets: dict[str, list[list[Path]]] = {"helm/tenant": [], "helm/product-base": []}
    for g in GROUPS:
        for f in sorted((ROOT / "argocd/generated" / g / "tenants").glob("*.yaml")):
            lint_sets["helm/tenant"].append([f])
    lint_sets["argocd/root"] = [[ROOT / f"argocd/root/values-{g}.yaml", ROOT / f"argocd/generated/{g}/root.yaml"] for g in GROUPS]

    snapshot: dict[Path, str] = {}
    manifests_for_policy: list[Path] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="gitops-check-"))
    try:
        for g in GROUPS:
            root_text = helm_template("argocd/root", "root", f"argocd-{g}",
                                      [ROOT / f"argocd/root/values-{g}.yaml", ROOT / f"argocd/generated/{g}/root.yaml"])
            root_objs = docs(root_text)
            secrets = [o for o in root_objs if o["kind"] == "Secret"]
            appsets = [o for o in root_objs if o["kind"] == "ApplicationSet"]
            snapshot[SNAPSHOT / g / "root.yaml"] = dump(root_objs)
            apps: list[dict] = []
            for a in appsets:
                try:
                    apps += expand(a, secrets)
                except TemplateError as e:
                    step(f"{g}: expand ApplicationSet {a['metadata']['name']}", False, str(e))
            step(f"{g}: root chart -> {len(appsets)} ApplicationSets -> {len(apps)} Applications", bool(apps))
            snapshot[SNAPSHOT / g / "applications.yaml"] = dump(sorted(apps, key=lambda a: a["metadata"]["name"]))

            rendered = 0
            for app in sorted(apps, key=lambda a: a["metadata"]["name"]):
                name = app["metadata"]["name"]
                src = app["spec"]["source"]
                if src.get("path") == "helm/product-base":
                    lint_sets["helm/product-base"].append(app_value_files(app))
                try:
                    text = render_app(app)
                except RuntimeError as e:
                    step(f"{g}: render {name}", False, str(e))
                    continue
                if text is None:
                    continue
                rendered += 1
                snapshot[SNAPSHOT / g / "manifests" / f"{name}.yaml"] = dump(docs(text))
                out = tmpdir / g / f"{name}.yaml"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                manifests_for_policy.append(out)
            step(f"{g}: helm template of {rendered} in-repo Applications", True)
            (tmpdir / f"root-{g}.yaml").write_text(root_text, encoding="utf-8")
            (tmpdir / f"apps-{g}.yaml").write_text(snapshot[SNAPSHOT / g / "applications.yaml"], encoding="utf-8")

        # Lint: every chart with every values combination it is deployed with
        for chart, sets in lint_sets.items():
            errors = []
            for files in sets:
                cmd = ["helm", "lint", chart, "--quiet"]
                for f in files:
                    cmd += ["-f", str(f)]
                r = run(cmd)
                if r.returncode:
                    errors.append(r.stdout + r.stderr)
            step(f"helm lint {chart} ({len(sets)} value sets)", not errors, "\n".join(errors[:2]))

        if not args.offline:
            if not shutil.which("kubeconform"):
                step("kubeconform", False, "kubeconform is not installed (use --offline to skip)")
            else:
                cache = Path(tempfile.gettempdir()) / "kubeconform-cache"
                cache.mkdir(exist_ok=True)
                r = run(["kubeconform", "-strict", "-summary", "-kubernetes-version", K8S_VERSION,
                         "-schema-location", "default", "-schema-location", CRD_SCHEMAS,
                         "-cache", str(cache), *(["-skip", SKIP_KINDS] if SKIP_KINDS else []), str(tmpdir)])
                step(f"kubeconform -strict (Kubernetes {K8S_VERSION} + CRDs)", r.returncode == 0,
                     "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "is invalid" in l or "failed" in l.lower() or "Summary" in l))
                if r.returncode == 0:
                    print("     " + r.stdout.strip().splitlines()[-1])

        r = run([sys.executable, "policy/check_manifests.py", *map(str, manifests_for_policy)])
        step(f"policy/check_manifests.py ({len(manifests_for_policy)} rendered Applications)", r.returncode == 0, r.stdout + r.stderr)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Snapshot for reviewers
    existing = {p.relative_to(ROOT) for p in (ROOT / SNAPSHOT).rglob("*.yaml")} if (ROOT / SNAPSHOT).exists() else set()
    header = "# GENERATED by scripts/gitops-check.py. Do not edit.\n"
    changed = [p for p, t in snapshot.items() if not (ROOT / p).exists() or (ROOT / p).read_text(encoding="utf-8") != header + t]
    stale = sorted(existing - set(snapshot))
    if args.check:
        step("examples/rendered/ snapshot up to date", not changed and not stale,
             "\n".join(f"stale: {p.as_posix()}" for p in changed + stale))
    else:
        for p in stale:
            (ROOT / p).unlink()
        for p in changed:
            (ROOT / p).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / p).write_text(header + snapshot[p], encoding="utf-8", newline="\n")
        print(f"     examples/rendered/: {len(changed)} written, {len(stale)} removed")

    print(f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
