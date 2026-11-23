# Security operations: Falco, Security Command Center, audit

Depth: configuration and documentation (skeleton, as the brief specifies). The controls run on the
platform; this page shows where each finding goes.

## Detection sources
| Source | Covers | Config |
|---|---|---|
| **Falco** (DaemonSet on every cluster, modern eBPF) | Runtime behaviour in containers | `argocd/root/values.yaml` → `addons[falco].values.customRules` |
| **Security Command Center** (Premium, org level) | Misconfigurations, vulnerabilities, threats (Event Threat Detection, Container Threat Detection), VPC-SC violations | Activated once at the organization by an org admin (rollout step; the API is enabled in the security projects by L1); findings exported to Pub/Sub |
| **GKE Security Posture** | Workload configuration and OS/language vulnerabilities per cluster | `modules/gke-cluster` (`security_posture_config`) |
| **Artifact Analysis** | Image vulnerabilities at build time (gate) and continuously | `ci-templates/scripts/build-sign.sh scan` |
| **Cloud Audit Logs** | Admin activity everywhere; data access on Cloud SQL, KMS, GCS and BigQuery for prod | Every project's audit logs go to the central audit bucket (`modules/project-factory` sink, bucket from `modules/platform`). Data Access logs are switched on at the organization by the security team (rollout step) |

## Platform Falco rules
| Rule | Priority | Why |
|---|---|---|
| Shell in a tenant container | CRITICAL | Tenant workloads never need an interactive shell. `exec` is disabled in ArgoCD, and operators use Connect Gateway with audit. |
| Tenant egress bypassing the egress gateway | WARNING | Egress must pass through the Istio egress gateway allowlist (ServiceEntry). A direct connection means a policy gap. |
| Write below binary directories in a tenant container | CRITICAL | Tenant images run with a read-only root filesystem, so a write there means tampering. |

Falco writes JSON to stdout, which goes to Cloud Logging. Log-based metrics and alerts fire on `priority >= WARNING`. CRITICAL findings page the on-call SRE and security.

## Routing
```
Falco ─┐
SCC ───┼─> Pub/Sub topic security-findings (security-prod)
Audit ─┘      ├─> alerting: page on CRITICAL / HIGH, ticket on MEDIUM
              └─> BigQuery dataset security_findings (1 year), for the SOC 2 evidence and reviews
```

## Reviews (SOC 2 evidence)
| Cadence | Review |
|---|---|
| Daily | New CRITICAL and HIGH findings triaged (owner and due date) |
| Weekly | Binary Authorization break-glass uses ([runbooks/break-glass.md](runbooks/break-glass.md)), VPC-SC dry-run and enforced violations, drift reports |
| Monthly | IAM recommender findings, unused service accounts, isolation-test history |
| Quarterly | DR test results ([runbooks/dr.md](runbooks/dr.md)), access reviews of the GitHub Environments' reviewers |
