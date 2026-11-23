# Database bootstrap job

This job applies the database-level isolation that Terraform deliberately doesn't apply, because
Terraform never connects to a database. See [architecture §8](../docs/architecture.md#8-data-architecture).

| Step | SQL |
|---|---|
| Close the database | `REVOKE CONNECT, TEMPORARY ON DATABASE … FROM PUBLIC`, `REVOKE ALL ON SCHEMA public FROM PUBLIC` |
| Open it to one login | `GRANT CONNECT, TEMPORARY ON DATABASE … TO "<customer>-<env>@<project>.iam"` |
| Product schemas | `CREATE SCHEMA IF NOT EXISTS <product> AUTHORIZATION <login>` for each enabled product |
| Marker | `_platform.bootstrap(grant_hash, login, schemas)`. The release gate runs `--verify` and fails if the current hash is missing. |

- **Where it runs:** `db-bootstrap-<region>` is a Cloud Run job in `data-nonprod` / `data-prod`, created by L2.
- **Identity:** it logs in as `db-bootstrap@<data project>`, an IAM database user holding `cloudsqlsuperuser`. Terraform assigns that role through the Cloud SQL Admin API (verification V10).
- **How it's started:** the pipeline runs it right after each L3 apply, with the L3 `bootstrap` output:

```bash
gcloud run jobs execute db-bootstrap-us-east1 --region us-east1 --project pfx-data-prod --wait \
  --args="--instance=pfx-data-prod:us-east1:sql-prod-us-east1-01,--database=acme_corp_prod,--login=acme-corp-prod@pfx-compute-prod.iam,--schemas=payment,reporting"
```

Offline tests: `python -m pytest db-bootstrap`.

**To verify on a real instance (rollout step):** whether `cloudsqlsuperuser` may run
`GRANT <iam login> TO CURRENT_USER` for IAM users that Cloud SQL created. If it can't, the
fallback is to create each schema as the bootstrap login and then `GRANT USAGE, CREATE` to the
environment login.
