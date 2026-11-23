# Data flows inside one customer's boundary (architecture §9)

Depth: **skeleton plus documentation**, as the brief specifies. The planning and guard logic is
complete and unit-tested offline (`pytest data-flows`). Each step maps to one Google API call; those
calls are proven during the rollout (see [`docs/what-is-mocked.md`](../docs/what-is-mocked.md)).
Only GCP-native services move data: Cloud SQL export/import, BigQuery `EXPORT DATA` and load jobs,
and Storage Transfer Service. There is no custom ETL.

| Flow | Direction | Code | Runs as / where |
|---|---|---|---|
| Shared reference | promoter → all 4 envs read | Terraform `modules/data-sharing` (bucket + dataset + IAM) | `promoter@platform-prod` writes; env identities read |
| Seed down | prod → uat / stage / dev | [`seed-down/main.py`](seed-down/main.py) (prod side), [`seed-down/import_job.py`](seed-down/import_job.py) (non-prod side) | `seed-publisher@data-prod` (Cloud Function), then `seed-import@data-nonprod` (Cloud Run job) |
| Promote up | dev → stage → uat → prod | [`promote-up/promote_up.py`](promote-up/promote_up.py) + [`.github/workflows/promote-up.yml`](../.github/workflows/promote-up.yml) | source pool exports; `promoter` publishes after approval; target pool imports |

## Seed down

```
Cloud Scheduler / on demand
  └─ seed-down function (data-prod, prod perimeter)
       guard: target listed in data-sharing.yaml, sanitized mode, version-compatibility window
       1  export acme_corp_prod            -> gs://pfx-seed-work-<region>/...   (2-day lifecycle)
       2  create scratch instance          private IP, prod CMEK key, same region
       3  import into scratch
       4  sanitize.sql.tmpl per schema     (+ products/<p>/data/sanitize.sql), one transaction
       5  verify.sql.tmpl per schema       any violation: stop, alert, keep scratch for inspection
       6  role-mapping.sql.tmpl            NOLOGIN role = target login, REASSIGN OWNED, _platform.clone_metadata
       7  export sanitized dump            -> gs://pfx-<customer>-seed/sql/<run>/<target>.sql.gz
       8  delete scratch instance
       9  BigQuery anonymize.sql           EXPORT DATA (Parquet) -> seed bucket
      10  Storage Transfer                 product buckets -> seed bucket (excluded prefixes)
      11  manifest                         -> gs://pfx-<customer>-seed/manifests/<run>.json
  └─ Eventarc on the manifest -> import job (data-nonprod, non-prod perimeter)
       drop + recreate acme_corp_<target>, import AS the target login (V10), rerun db-bootstrap,
       load Parquet into the target datasets, copy objects into the target buckets
```

The seed bucket lives in `data-exchange`, uses the customer's exchange key, and deletes objects
after 7 days. PVCs and Pub/Sub messages are excluded. Raw prod data never leaves the prod perimeter;
only the verified, sanitized copy does.

**Sanitization** ([`sql/sanitize.sql.tmpl`](sql/sanitize.sql.tmpl)) covers the auth tables every
product contains (users, sessions, tokens) and the common optional tables (API keys, webhooks,
OAuth clients, integrations, payment methods). Product teams add product-specific PII rules in
`products/<product>/data/sanitize.sql`. [`sql/verify.sql.tmpl`](sql/verify.sql.tmpl) must
return zero violations, or the run stops.

## Promote up

Three hops, each with its own identity:
1. Export: the source environment's runner pool calls the product's config export API and stages the package in the source environment's own bucket.
2. Publish: after the approvals in `data-sharing.yaml` (GitHub Environment `promote-<target>` reviewers), the `promoter` copies the package to the shared bucket's `promote/` prefix.
3. Import: the target environment's pool imports it.

Promotions go exactly one step up. Every promoted product must support export (`supportsExport`), and the target version must be able to read the package.

```bash
python data-flows/promote-up/promote_up.py --customer acme-corp --product payment-api --from uat --to prod
```
