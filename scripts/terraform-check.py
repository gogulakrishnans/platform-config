#!/usr/bin/env python3
"""Offline Terraform gate: fmt -check, init -backend=false, validate, and test (mock providers).

No credentials are needed. Used by CI (.github/workflows) and locally.

    python scripts/terraform-check.py                 # all modules and layers
    python scripts/terraform-check.py modules/kms     # selected directories (relative to infrastructure/)
    python scripts/terraform-check.py --no-test       # skip terraform test
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "infrastructure"


def tf_dirs(selected: list[str]) -> list[Path]:
    if selected:
        return [INFRA / s for s in selected]
    dirs = {p.parent for p in INFRA.rglob("*.tf") if ".terraform" not in p.parts and "tests" not in p.parts}
    return sorted(dirs)


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, "TF_IN_AUTOMATION": "1"})
    return proc.returncode, (proc.stdout + proc.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*")
    ap.add_argument("--no-test", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    tf = shutil.which("terraform")
    if not tf:
        print("terraform not found", file=sys.stderr)
        return 1
    os.environ.setdefault("TF_PLUGIN_CACHE_DIR", str(Path.home() / ".terraform.d" / "plugin-cache"))
    Path(os.environ["TF_PLUGIN_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)

    code, out = run([tf, "fmt", "-check", "-recursive", "-diff"], INFRA)
    print(f"{'ok  ' if code == 0 else 'FAIL'} terraform fmt -check -recursive")
    if code:
        print(out)
    failures = int(code != 0)

    for d in tf_dirs(args.dirs):
        rel = d.relative_to(INFRA).as_posix()
        steps = [("init", [tf, "init", "-input=false", "-backend=false", "-no-color"]),
                 ("validate", [tf, "validate", "-no-color"])]
        if not args.no_test and (d / "tests").is_dir():
            steps.append(("test", [tf, "test", "-no-color"]))
        for name, cmd in steps:
            code, out = run(cmd, d)
            if code:
                print(f"FAIL {rel}: {name}")
                print(out[-6000:])
                failures += 1
                break
        else:
            print(f"ok   {rel}" + ("" if args.quiet else f" ({', '.join(n for n, _ in steps)})"))
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
