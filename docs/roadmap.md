# 12-week roadmap

Team: 5 platform engineers (two on infrastructure, one on GitOps and delivery, one on data and security, one SRE).
MVP at week 4, production-ready at week 12. Each phase ends with an exit review against the
criteria below. A miss moves scope, not the date.

```mermaid
gantt
    title Platform roadmap (weeks 1-12)
    dateFormat  YYYY-MM-DD
    axisFormat  W%W
    section MVP (1-4)
    L0 bootstrap + L1 foundation (dry-run perimeters)   :a1, 2027-01-04, 10d
    One region pair: L2 cells, SQL + replicas, edge     :a2, after a1, 7d
    ArgoCD x3, tenant + product charts, GitOps index    :a3, 2027-01-11, 12d
    Repo gate in CI, apply pipeline on GitHub-hosted    :a4, 2027-01-04, 14d
    First 2 customers end to end (dev..prod)            :milestone, m1, 2027-01-29, 0d
    section Hardening + data flows (5-8)
    Self-hosted pools, VPC-SC enforced                  :b1, 2027-02-01, 10d
    Binary Authorization + promotion by digest          :b2, 2027-02-01, 10d
    Argo Rollouts canary, Cloud Run + MIG delivery      :b3, 2027-02-08, 10d
    Seed down + sanitization, promote up, shared ref    :b4, 2027-02-08, 15d
    Isolation tests live, drift detection               :b5, 2027-02-15, 10d
    section Rollout + DR (9-12)
    Second region pair, capacity runbooks exercised     :c1, 2027-03-01, 10d
    DR tests per cell (switchover), ArgoCD rebuild drill :c2, 2027-03-08, 10d
    Customer waves: 10 -> 50 -> 200                      :c3, 2027-03-08, 20d
    SOC 2 evidence review, production readiness         :milestone, m2, 2027-03-26, 0d
```

## Weeks 1–4: MVP
| Week | Deliverables | Exit criteria |
|---|---|---|
| 1 | Org prerequisites, L0 (seed project, state bucket, WIF for GitHub/Bitbucket), L1 apply from GitHub-hosted runners (perimeters in **dry-run**) | 12 projects exist with labels, budgets, audit sinks, and Shared VPCs |
| 2 | L2 for `us-east1` + `us-central1`: cells, prod DR clusters, Cloud SQL + DR replicas, inventory write-back; L2 edge | Inventory files written by L2, not by hand |
| 3 | ArgoCD ×3 with root Applications; add-ons; tenant and product charts; GitOps index | Both example customers' tenant and product Applications Healthy |
| 4 | Onboarding automation (`customer-pr` → apply waves → bootstrap job); first real pilot customer | **A region-only PR gives 4 environments in < 30 min** |

## Weeks 5–8: hardening and data flows
| Week | Deliverables | Exit criteria |
|---|---|---|
| 5 | Self-hosted runner pools per group; apply moves to the pools; **VPC-SC enforced** | No dry-run violations for 5 days before enforcement |
| 6 | Binary Authorization enforced in prod (`promoted`), image promotion by digest, break-glass alerting | An unpromoted image is rejected in prod |
| 7 | Progressive delivery on all three runtimes with automatic rollback; version waves bot | A failing canary rolls back on GKE, Cloud Run and MIG |
| 8 | Seed down (sanitize, verify, role mapping), promote up, shared reference; isolation tests live; drift detection | Seed down < 30 min with zero verify violations; isolation suite green |

## Weeks 9–12: rollout and DR
| Week | Deliverables | Exit criteria |
|---|---|---|
| 9 | Second region pair through the region runbook; cell capacity runbook exercised | New region with one platform PR, project count still 12 |
| 10 | DR switchover test per prod cell; Prod ArgoCD rebuild drill | Warm standby RTO ≤ 30 min, RPO ≤ 5 min measured |
| 11 | Customer waves: 10 → 50 | SLOs held in each wave; no isolation failures |
| 12 | Waves to 200; SOC 2 evidence pack (audit, reviews, DR, isolation history); handover | Production readiness review signed off |

## Product catalog timeline
| Week | Catalog | Runtime path proven |
|---|---|---|
| 2 | `payment-api` (GKE, Cloud SQL, GCS, Pub/Sub publisher, egress allowlist) | Tenant + product charts, Argo Rollouts |
| 4 | `reporting-engine` (Cloud Run, Pub/Sub push subscriber, BigQuery) | Serverless NEG, revision traffic split |
| 6 | `legacy-billing` (MIG, Packer + Ansible) | Golden image promotion, MIG canary |
| 8 | `document-index` (GKE stateful, approved PVC) | StatefulSet, Backup for GKE restore |
| 9–12 | Remaining products (15–20 total) onboarded through catalog PRs, 2–3 per week | Each passes `validate-registry`, gets its Helm values layer and sanitize rules |

## Risks to the timeline
| Risk | Mitigation |
|---|---|
| VPC-SC enforcement breaks a pipeline late | Dry-run from week 1, violations reviewed weekly; enforcement gated on 5 clean days |
| Quota increases (Cloud Run services, SQL instances, certificates) take days | Quota preferences filed in week 1 for both region pairs (project factory) |
| Product teams late with export/import or sanitize rules | Promote-up and seed down stay disabled per customer (`data-sharing.yaml`) until the product supports them; the validator enforces it |
| DR test misses its RTO | Week 10 leaves two weeks to fix before production readiness; hot standby is available per customer |
