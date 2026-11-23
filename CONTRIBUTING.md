# Contributing

## Ground rules
- **Never commit real identifiers or secrets.** Organization, billing, project IDs and numbers, domains and customer names stay placeholders. Real values live in the private overlay ([docs/what-is-mocked.md](docs/what-is-mocked.md)). gitleaks runs on every PR.
- **Do not edit generated files by hand.** CI regenerates them and fails on any difference:
  - `infrastructure/layers/L2-*`, `infrastructure/layers/L3-customer/*` (generate-layers)
  - `argocd/generated/` (render-gitops)
  - `docs/catalog.md` (catalog-report)
  - `examples/rendered/` (gitops-check)
  - `customers/*/customer.yaml` `placement:` (placement job)
  - `products/*/releases.yaml` (promotion pipeline)
- **Locked decisions** in [docs/decisions.md](docs/decisions.md) change only through an approved design PR that updates the decision record.

## Kinds of change
| Change | Files | Who approves |
|---|---|---|
| Onboard or change a customer | `customers/<id>/` | Customer Success + platform ([runbook](docs/runbooks/onboarding.md)) |
| Add or change a catalog product | `products/<product>/product.yaml` | Platform engineering |
| Product Helm values | `products/<product>/helm/` | The owning product team |
| Capacity (cell) or region | `inventory/regions.yaml` | Platform engineering ([runbook](docs/runbooks/capacity.md)) |
| Shared Terraform modules, L1, VPC-SC, project factory | `infrastructure/` | Platform + security (CODEOWNERS) |
| Charts, ArgoCD | `helm/`, `argocd/` | Platform engineering |
| Data flows | `data-flows/` | Platform + security |

## Before you open a PR
```bash
pip install -r requirements-dev.txt
python scripts/validate-registry.py
python scripts/generate-layers.py && python scripts/render-gitops.py && python scripts/catalog-report.py
python scripts/terraform-check.py --quiet
python policy/check_terraform.py
python scripts/gitops-check.py
python -m pytest -q scripts db-bootstrap data-flows policy tests/isolation
```

## Conventions
- **Terraform:**
  - Every module takes `labels` from the `labels` module (the six mandatory labels).
  - Google APIs only, with no `kubernetes` or `postgresql` providers.
  - Prod data uses `deletion_policy = "PREVENT"`.
  - Pin the provider as `>= 8.0, < 9.0`.
- **Helm:**
  - Charts use `apiVersion: v2` (Helm 3).
  - Every chart has a strict `values.schema.json`.
  - Pods meet the Pod Security "restricted" profile.
  - Prod images are referenced by digest.
- **Workflows:**
  - Pin third-party actions to a commit SHA.
  - Pull-request workflows get a read-only token and never use self-hosted runners.
  - Pass untrusted inputs through `env:`, never inline in `run:`.
- **Commits:** small and focused. The PR description lists the states the change will apply. The `customer-pr` job writes that list.

## Reporting a security issue
Do not open a public issue. Contact the platform security team through the private channel listed in the internal handbook.
