"""Offline tests for the database bootstrap job's SQL generation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bootstrap as b  # noqa: E402

LOGIN = "acme-corp-prod@pfx-compute-prod.iam"


def spec(**kw):
    args = {"database": "acme_corp_prod", "login": LOGIN, "schemas": ("payment", "reporting")}
    args.update(kw)
    return b.Spec(**args)


def test_public_is_revoked_before_anything_is_granted():
    stmts = b.plan(spec())
    revoke = stmts.index('REVOKE CONNECT, TEMPORARY ON DATABASE "acme_corp_prod" FROM PUBLIC')
    grant = stmts.index(f'GRANT CONNECT, TEMPORARY ON DATABASE "acme_corp_prod" TO "{LOGIN}"')
    assert revoke < grant


def test_only_the_environment_login_is_granted_connect():
    grants = [s for s in b.plan(spec()) if s.startswith("GRANT CONNECT")]
    assert grants == [f'GRANT CONNECT, TEMPORARY ON DATABASE "acme_corp_prod" TO "{LOGIN}"']


def test_one_schema_per_product_owned_by_the_login():
    stmts = b.plan(spec())
    for s in ("payment", "reporting"):
        assert f'CREATE SCHEMA IF NOT EXISTS "{s}" AUTHORIZATION "{LOGIN}"' in stmts
        assert f'REVOKE ALL ON SCHEMA "{s}" FROM PUBLIC' in stmts


def test_statements_are_idempotent_forms():
    for s in b.plan(spec()):
        if s.startswith("CREATE"):
            assert "IF NOT EXISTS" in s


def test_marker_records_the_grant_hash():
    s = spec()
    assert any(s.grant_hash in stmt for stmt in b.plan(s) if stmt.startswith("INSERT INTO _platform.bootstrap"))


def test_grant_hash_is_order_independent_and_changes_with_schemas():
    assert spec(schemas=("reporting", "payment")).grant_hash == spec().grant_hash
    assert spec(schemas=("payment",)).grant_hash != spec().grant_hash


def test_identifiers_are_quoted():
    assert b.quote_ident('a"b') == '"a""b"'
    assert b.quote_literal("o'k") == "'o''k'"


@pytest.mark.parametrize("bad", [
    {"database": "Acme"}, {"database": "acme;drop"}, {"database": "1acme"},
    {"login": "postgres"}, {"login": "acme@x.iam.gserviceaccount.com"},
    {"schemas": ("public",)}, {"schemas": ("_platform",)}, {"schemas": ("pay ment",)},
    {"schemas": ("payment", "payment")},
])
def test_rejects_unsafe_input(bad):
    with pytest.raises(ValueError):
        spec(**bad)


def test_verify_checks_public_and_schema_ownership():
    checks = b.verify_queries(spec())
    assert "public_cannot_connect" in checks and "marker_current" in checks
    assert {"schema_payment_owned_by_login", "schema_reporting_owned_by_login"} <= set(checks)


def test_cli_dry_run_prints_sql(capsys):
    rc = b.main(["--instance", "p:r:i", "--database", "acme_corp_prod", "--login", LOGIN,
                 "--schemas", "payment,reporting", "--dry-run"])
    assert rc == 0
    assert "REVOKE CONNECT" in capsys.readouterr().out


def test_cli_rejects_bad_login():
    assert b.main(["--instance", "p:r:i", "--database", "acme_corp_prod", "--login", "x", "--dry-run"]) == 2
