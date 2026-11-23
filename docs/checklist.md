# Final checklist

Each deliverable (D1–D5) and repo acceptance criterion from the brief, with where it is met and how it is checked.

## Deliverables
| # | Deliverable | Where | Checked by |
|---|---|---|---|
| D1 | Architecture design, decisions table, traceability table | [architecture.md](architecture.md) (§1–§22, C1–C23, §21 traceability), [decisions.md](decisions.md) (#1–#27), [gcp-verification.md](gcp-verification.md) (V1–V11) | Review |
| D2 | Three runtime diagrams, Mermaid + SVG | [gke](diagrams/gke.md), [cloud-run](diagrams/cloud-run.md), [instance-group](diagrams/instance-group.md) (Google Cloud icon diagrams, SVG + PNG, with legends); Mermaid + SVG in [diagrams/backup/](diagrams/backup/); 8 supporting diagrams | `render-diagrams.py --check` |
| D3 | Terraform L0–L3, two example customers; fmt, validate, `terraform test` with mock providers | `infrastructure/` (25 modules, L0 script, L1, generated L2-region, L2-edge and L3 roots) | `terraform-check.py` (every module and root), tflint, `policy/check_terraform.py` |
| D4 | Product base chart and tenant chart, values layering; `helm lint`, `helm template`, schema validation for the example customers | `helm/`, `argocd/`, `examples/rendered/` | `gitops-check.py` (lint, ApplicationSet expansion, template, kubeconform `-strict`, manifest policy) |
| D5 | Public GitHub repository `platform-config` | This repository: README, CONTRIBUTING, LICENSE, what-is-mocked, CI | `repo-gate.yml`; **published only on the owner's request** |

## Repo acceptance criteria
| Criterion | Status |
|---|---|
| D1–D5 present; the traceability table maps every scenario item and deliverable | ✓ ([§21](architecture.md#21-scenario-traceability)) |
| The three runtime diagrams exist as Mermaid and SVG | ✓ Mermaid + SVG in `docs/diagrams/backup/`; the pages show the Google Cloud icon versions |
| The repo gate passes in CI | All checks pass locally. They run in GitHub Actions once the repository is pushed. actionlint, gitleaks, ansible-lint and full `packer validate` run only in CI. |
| The two example customers render end to end: placement, L3 Terraform, tenant chart and product releases, ApplicationSet output | ✓ placement written by the job; L3 `terraform test` for both; `examples/rendered/{devstage,uat,prod}/applications.yaml` and `manifests/` |
| No secrets or real identifiers | ✓ placeholders only ([what-is-mocked.md](what-is-mocked.md)); gitleaks in CI; `.gitignore` for state, tfvars and the backend config |

## Public-repository constraints
| Constraint | Where |
|---|---|
| Fork PRs run only offline checks, no secrets, no self-hosted runners | `repo-gate.yml` (`pull_request`, read-only token, `ubuntu-latest`); `customer-pr.yml` write job only for same-repo branches |
| Apply only from the protected branch with required reviewers (GitHub Environments) | `terraform-apply.yml` (push to `main`), `_terraform-wave.yml` (`tf-<pool>` environments) |
| Self-hosted runners documented as the production configuration, never reachable from forks | §15, `runner-pools` module, workflows use them only on `push`, `schedule` or `workflow_dispatch` |
| Remote GCS backend as a template | `infrastructure/backend.hcl.example` |
| README (purpose, structure, quickstart, apply order L0→L4), CONTRIBUTING, LICENSE, what-is-mocked | ✓ |

## Platform targets (proven during the real rollout)
Each target is tracked in [roadmap.md](roadmap.md) with its exit criterion:
- onboarding in under 30 minutes
- a product added in under 20 minutes
- zero-downtime rollouts with rollback on all three runtimes
- isolation tests green
- seed down in under 30 minutes
- DR RTO/RPO
- 12 projects
- mandatory labels on every resource

## Repository URL
Not created yet. It will be pushed to the owner's GitHub account (`platform-config`) only when the owner asks.
