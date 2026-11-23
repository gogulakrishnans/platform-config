"""Tenant isolation tests (architecture §10).

Offline (repo gate): the case generator covers every container kind for every ordered pair.
Live (ISOLATION_LIVE=1, .github/workflows/isolation-tests.yml on a self-hosted pool): impersonates
customer A's env GSA and asserts every access to customer B's containers is DENIED. Skeleton: the
per-kind probes are listed; each is a single API call proven during the rollout.
"""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cases import KINDS, actor_identity, build_cases  # noqa: E402

REPO = HERE.parents[1]
LIVE = os.environ.get("ISOLATION_LIVE") == "1"


# ----------------------------------------------------------------------------- offline

def test_every_kind_is_covered_in_prod():
    cases = build_cases(REPO, "prod")
    assert {c.kind for c in cases} == set(KINDS)
    pairs = {(c.actor, c.target) for c in cases}
    assert pairs == {("acme-corp", "beta-industries"), ("beta-industries", "acme-corp")}


def test_cases_target_the_other_customer_only():
    for c in build_cases(REPO, "uat"):
        assert c.actor != c.target
        assert c.target in c.resource or c.target.replace("-", "_") in c.resource


def test_dev_and_stage_are_separate_targets():
    dev = {c.resource for c in build_cases(REPO, "dev")}
    stage = {c.resource for c in build_cases(REPO, "stage")}
    assert dev.isdisjoint(stage)


def test_sampling_is_bounded_and_deterministic():
    a = build_cases(REPO, "prod", sample=1, seed=7)
    b = build_cases(REPO, "prod", sample=1, seed=7)
    assert a == b and len({(c.actor, c.target) for c in a}) == 1


def test_actor_identity():
    assert actor_identity(REPO, "acme-corp", "stage") == "acme-corp-stage@pfx-compute-devstage.iam.gserviceaccount.com"


# ----------------------------------------------------------------------------- live

ENV = os.environ.get("ISOLATION_ENV", "uat")
LIVE_CASES = build_cases(REPO, ENV, sample=int(os.environ.get("ISOLATION_SAMPLE", "20"))) if LIVE else []


@pytest.mark.skipif(not LIVE, reason="needs a real environment (ISOLATION_LIVE=1)")
@pytest.mark.parametrize("case", LIVE_CASES, ids=lambda c: c.id)
def test_access_is_denied(case):  # pragma: no cover - runs only against GCP
    from probes import probe   # per-kind API calls under the actor's impersonated credentials

    allowed = probe(case, actor_identity(REPO, case.actor, case.env))
    assert allowed is False, f"ISOLATION BREACH: {case.actor} could {case.action} {case.kind} {case.resource}"
