#!/usr/bin/env python3
"""Database bootstrap job (architecture §8).

Platform-owned Cloud Run job, run by the pipeline right after each L3 apply with the L3 `bootstrap`
output. For one customer database it:

  1. revokes CONNECT and TEMP from PUBLIC (no other login can ever connect),
  2. grants CONNECT and TEMP to the customer's environment login only,
  3. pre-creates one schema per enabled product, owned by that login,
  4. writes a `_platform.bootstrap` marker with a hash of the grant set (release gate).

It is idempotent and logs in as its own IAM service account (cloudsqlsuperuser, assigned through
the Cloud SQL Admin API by Terraform). Terraform never connects to a database.

    python bootstrap.py --instance pfx-data-prod:us-east1:sql-prod-us-east1-01 \
        --database acme_corp_prod --login acme-corp-prod@pfx-compute-prod.iam \
        --schemas payment,reporting
    python bootstrap.py ... --verify      # read-only check used by the release gate
    python bootstrap.py ... --dry-run     # print the SQL only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass

IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
LOGIN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam$")
RESERVED_SCHEMAS = {"public", "_platform", "pg_catalog", "information_schema"}


def quote_ident(name: str) -> str:
    """Quote a PostgreSQL identifier (handles the @ and . in IAM login names)."""
    if "\x00" in name:
        raise ValueError("NUL in identifier")
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class Spec:
    database: str
    login: str
    schemas: tuple[str, ...]

    def __post_init__(self) -> None:
        if not IDENT.match(self.database):
            raise ValueError(f"invalid database name {self.database!r}")
        if not LOGIN.match(self.login):
            raise ValueError(f"invalid IAM login {self.login!r} (expected <sa>@<project>.iam)")
        for s in self.schemas:
            if not IDENT.match(s) or s in RESERVED_SCHEMAS:
                raise ValueError(f"invalid product schema {s!r}")
        if len(set(self.schemas)) != len(self.schemas):
            raise ValueError("duplicate schemas")

    @property
    def grant_hash(self) -> str:
        canonical = json.dumps({"database": self.database, "login": self.login, "schemas": sorted(self.schemas)},
                               sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


def plan(spec: Spec) -> list[str]:
    """SQL statements, in order. Every statement is idempotent."""
    db, login = quote_ident(spec.database), quote_ident(spec.login)
    stmts = [
        f"REVOKE CONNECT, TEMPORARY ON DATABASE {db} FROM PUBLIC",
        f"REVOKE ALL ON SCHEMA public FROM PUBLIC",
        f"GRANT CONNECT, TEMPORARY ON DATABASE {db} TO {login}",
        # The bootstrap login must be a member of the env login to create schemas it owns.
        f"GRANT {login} TO CURRENT_USER",
    ]
    for schema in sorted(spec.schemas):
        s = quote_ident(schema)
        stmts += [
            f"CREATE SCHEMA IF NOT EXISTS {s} AUTHORIZATION {login}",
            f"ALTER SCHEMA {s} OWNER TO {login}",
            f"REVOKE ALL ON SCHEMA {s} FROM PUBLIC",
        ]
    stmts += [
        "CREATE SCHEMA IF NOT EXISTS _platform AUTHORIZATION CURRENT_USER",
        "REVOKE ALL ON SCHEMA _platform FROM PUBLIC",
        "CREATE TABLE IF NOT EXISTS _platform.bootstrap ("
        "applied_at timestamptz NOT NULL DEFAULT now(), grant_hash text NOT NULL, "
        "login text NOT NULL, schemas text[] NOT NULL)",
        "INSERT INTO _platform.bootstrap (grant_hash, login, schemas) VALUES ("
        f"{quote_literal(spec.grant_hash)}, {quote_literal(spec.login)}, "
        f"ARRAY[{', '.join(quote_literal(s) for s in sorted(spec.schemas))}]::text[])",
    ]
    return stmts


def verify_queries(spec: Spec) -> dict[str, str]:
    """Read-only checks for the release gate; each query must return true."""
    db = quote_literal(spec.database)
    login = quote_literal(spec.login)
    checks = {
        "public_cannot_connect": f"SELECT NOT has_database_privilege('public', {db}, 'CONNECT')",
        "login_can_connect": f"SELECT has_database_privilege({login}, {db}, 'CONNECT')",
        "marker_current": "SELECT EXISTS (SELECT 1 FROM _platform.bootstrap WHERE grant_hash = "
                          f"{quote_literal(spec.grant_hash)})",
    }
    for s in spec.schemas:
        checks[f"schema_{s}_owned_by_login"] = (
            f"SELECT EXISTS (SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
            f"WHERE n.nspname = {quote_literal(s)} AND r.rolname = {login})")
    return checks


def connect(instance: str, database: str):  # pragma: no cover - needs a real instance
    from google.cloud.sql.connector import Connector, IPTypes

    connector = Connector(refresh_strategy="lazy")
    admin = os.environ.get("BOOTSTRAP_LOGIN")  # e.g. db-bootstrap@pfx-data-prod.iam
    if not admin:
        raise SystemExit("BOOTSTRAP_LOGIN is not set")
    return connector.connect(instance, "pg8000", user=admin, db=database,
                             enable_iam_auth=True, ip_type=IPTypes.PRIVATE)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", required=True, help="PROJECT:REGION:INSTANCE")
    ap.add_argument("--database", required=True)
    ap.add_argument("--login", required=True)
    ap.add_argument("--schemas", default="", help="comma-separated product schemas")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    try:
        spec = Spec(args.database, args.login, tuple(s for s in args.schemas.split(",") if s))
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(";\n".join(plan(spec)) + ";")
        return 0

    conn = connect(args.instance, spec.database)  # pragma: no cover
    try:  # pragma: no cover
        cur = conn.cursor()
        if args.verify:
            failed = []
            for name, sql in verify_queries(spec).items():
                cur.execute(sql)
                if not cur.fetchone()[0]:
                    failed.append(name)
            print(json.dumps({"database": spec.database, "failed": failed}))
            return 1 if failed else 0
        for stmt in plan(spec):
            cur.execute(stmt)
        conn.commit()
        print(json.dumps({"database": spec.database, "grant_hash": spec.grant_hash, "status": "applied"}))
        return 0
    finally:  # pragma: no cover
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
