# Phase 1 verification: GCP limits and features

Checked against Google Cloud documentation on 2026-11-23. Each item states the finding, its effect on the design, and the action taken. "Design adjusted" means this document changed the design; nothing here changes a locked decision.

Scale used for the arithmetic: 200 customers today, 500 as the design target, ~5 enabled products per customer, 4 environments.

## Summary

| # | Item | Result | Effect |
|---|---|---|---|
| V1 | Service accounts per project | Quota varies per project ("Service Account Count"); commonly 100 | Quota increase in L1 (planned in spec). Trigger documented. |
| V2 | Buckets and datasets at ~4,000 each | No limit on bucket count; no limit on dataset count | Fits. Bucket create rate (~1 per 2 s) shapes L3 apply. **Design adjusted** (rate-aware apply). |
| V3 | Cloud Run services per region per project | 1,000 services, 1,000 jobs per project per region (increasable) | **Does not fit at 500 customers** in `compute-devstage` and `compute-prod`. **Design adjusted** (quota tracked in inventory, checked by placement). |
| V4 | BigQuery cross-region copy per region pair | Scheduled cross-region dataset copy (DTS, ≥12 h interval) works between any regions | Fits the daily copy. **Design adjusted**: DR dataset pre-created with a CMEK key in the DR region. |
| V5 | KMS location for dual-region GCS and BigQuery replicas | Configurable dual-region bucket → key in the matching multi-region (`us`, `eu`); predefined dual-region → same code; BigQuery DR copy → key in the destination region | Matches Decision 8. Key ring locations fixed in the design. |
| V6 | Workload Identity Federation for GKE per service | GCS, BigQuery, Pub/Sub, KMS, Secret Manager accept KSA principals directly; Cloud SQL IAM login needs a service account or user | Matches Decision 8 (impersonate the customer environment GSA for Cloud SQL). |
| V7 | ArgoCD to private clusters | Private endpoint + control-plane global access + authorized networks works across regions. Google now recommends the DNS-based endpoint | **DNS-based endpoint adopted** with approval (decisions #22). |
| V8 | Certificate Manager limits | 1,000 Google-managed certs/project, 5,000 map entries/project, 100 maps/project, 4 certs per entry (fixed) | Fits 500 customers. **Design adjusted**: each customer cert carries the apex and the wildcard. |
| V9 | Cloud SQL DR replica and write endpoint | Enterprise Plus advanced DR: switchover (no data loss) and replica failover; write endpoint is a global DNS name that follows the primary. Needs private IP with PSA and the Cloud DNS API | Matches Decision 10. Cloud DNS API enabled in `data-prod` and `net-prod`. Fallback kept. |
| V10 | Cloud SQL import and role ownership | Every owner/grantee role in the dump must exist before import, or the import runs as a user who is a member of those roles | Confirms the seed-down role-mapping step (Decision 7 step 4). |
| V11 | VPC-SC: promotion job reads non-prod Artifact Registry; CMEK inside each perimeter | Cross-perimeter reads need an egress rule on the source perimeter and an ingress rule on the target perimeter | Rule pair defined below. Keys stay inside each perimeter. |

## Details

### V1. Service-account quota per project
- Google documents the limit as the per-project "Service Account Count" quota, and the default is commonly 100. Deleted accounts don't count.
- Demand per project (one GSA per customer per environment, Decision 8):

  | Project | 200 customers | 500 customers |
  |---|---|---|
  | `compute-devstage` (dev + stage) | 400 + platform | 1,000 + platform |
  | `compute-uat` | 200 + platform | 500 + platform |
  | `compute-prod` | 200 + platform | 500 + platform |

- **Action:** L1 requests a Service Account Count increase to 1,500 for the three compute projects. Trigger (already in the spec): if refused, add one identity project per environment group. The project factory makes that a single PR.
- Account IDs are `{customer}-{env}` (≤ 26 characters, inside the 30-character limit).
- The Cloud SQL IAM username is the email without `.gserviceaccount.com`: `{customer}-{env}@{project}.iam`. With a customer ID ≤ 20 and a project ID ≤ 30, the longest is 61 characters, inside PostgreSQL's 63. **Constraint added:** the compute project IDs must stay ≤ 30 characters (they do).

### V2. Buckets and datasets (~4,000 each)
- **Cloud Storage:** there is no limit to the number of buckets in a project or location. The limit that matters is the bucket **create/delete rate, about one request every two seconds per project**.
- **BigQuery:** the maximum number of datasets per project is unlimited. Dataset metadata updates are limited to 5 operations per 10 seconds per project.
- **Design adjusted:**
  - L3 applies run with a bounded parallelism and retry on 429 for bucket and dataset creation.
  - Onboarding one customer creates about 5 products × 4 environments = 20 buckets and 20 datasets. That takes about 40 s of creation time and fits the 30-minute target.
  - Bulk operations (mass re-creation in a DR test) are batched by the pipeline and never run as one apply.
- Dataset ACLs are limited to 2,500 authorized resources. We grant per dataset, not with authorized views, so this doesn't apply.

### V3. Cloud Run services per region per project
- The quota is **1,000 services and 1,000 jobs per project per region**. Google's quota page lists it as increasable. One architecture guide describes it as non-adjustable, so treat the increase as **not guaranteed**.
- Demand for the worst case, where all customers sit in one region and have 2 Cloud Run products. Each service has a migration job, so jobs ≈ services:

  | Project, region | 200 customers | 500 customers |
  |---|---|---|
  | `compute-devstage`, primary (dev + stage) | 800 | 2,000 |
  | `compute-uat`, primary | 400 | 1,000 |
  | `compute-prod`, primary region | 400 | 1,000 |
  | `compute-prod`, pair region (its own primaries + DR copies of the partner) | up to 800 | up to 2,000 |

- **Design adjusted:**
  1. `inventory/regions.yaml` gets a `quotas.cloudRunServices` value per environment group (default 1,000, raised when Google approves an increase).
  2. The placement job counts the Cloud Run services a customer would add (from `product.yaml` runtimes). In prod it counts them in **both** the primary region and the DR pair region. If the count would pass 80% of the quota, placement fails the PR and opens a **quota PR**.
  3. The quota PR either records an approved increase or, if Google refuses, triggers the spec's "add a shared project" rule: a second compute project for that environment group (for example `compute-devstage-2`). The project factory creates it, and inventory records which customers it hosts. Expect this only past ~250 customers per region. Note it in the risk register.
- Cloud Run functions share the same pool. The seed-down functions live in `data-prod`, so they don't consume compute-project quota.

### V4. BigQuery cross-region copy for each region pair
- The design uses a **daily cross-region dataset copy** (BigQuery Data Transfer Service, `cross_region_copy`), not managed cross-region replication. The minimum interval is 12 hours, so a daily copy is supported for any region pair. One run copies up to 1,000 tables, and larger datasets continue in later runs. Cost is network egress.
- For CMEK: a cross-region copy of CMEK tables fails unless the destination dataset is CMEK-encrypted. `--destination_kms_key` doesn't apply to dataset copies.
- **Design adjusted:**
  - L3 pre-creates the prod DR dataset `{customer}_{product}_prod_dr` in the pair region, with a default CMEK key from the customer's prod key ring in the pair region.
  - The transfer config writes into it.
  - The DR test confirms that the copied tables are readable.
- Managed cross-region replication and managed DR were considered and rejected. BigQuery holds analytics only (Decision 5), and RPO 24 h is accepted.

### V5. KMS key location for dual-region GCS and BigQuery replicas
- Configurable dual-region bucket (e.g. `us-east1` + `us-central1`): the key ring must be in the **associated multi-region** (`us`). Predefined dual-region (e.g. `nam4`): key ring in that same code. A multi-region resource cannot use a regional key.
- BigQuery datasets need a key in the dataset's location. The DR copy needs a key in the pair region (V4).
- **Result:** the per-customer prod key ring exists in three locations: the primary region (Cloud SQL envelope keys, PD, regional BigQuery), the pair region (DR BigQuery copy, DR PD restores), and the multi-region (dual-region buckets). Non-prod key rings exist only in the primary region. This matches Decision 8.

### V6. Workload Identity Federation for GKE, per service
- WIF for GKE lets IAM bind directly to a Kubernetes service account principal (`principal://iam.googleapis.com/projects/NUM/locations/global/workloadIdentityPools/PROJECT.svc.id.goog/subject/ns/NS/sa/KSA`). Cloud Storage (uniform bucket-level access), BigQuery, Pub/Sub, Cloud KMS and Secret Manager accept it.
- Cloud SQL IAM database users must be users, service accounts or groups, so a KSA principal can't be a database login. Pods impersonate the customer environment GSA (`roles/iam.workloadIdentityUser` on the GSA for that KSA) for Cloud SQL and for GCS signed URLs. This is the mechanism in Decision 8.
- Limitations to design around: pods on the host network don't get WIF, which we don't allow anyway. The GKE metadata server is capped at 500 concurrent connections per node. The first seconds after pod start can fail auth, so the base chart sets retry on startup.

### V7. ArgoCD access to private clusters
- With control-plane global access on and authorized networks enforced on the internal endpoint, any client in the same VPC (any region) on an authorized range can reach the private endpoint. The management cluster is in the same Shared VPC as its group's clusters, so the design works. Cross-region traffic is billed as egress.
- Google's hardening guide now recommends the **DNS-based control-plane endpoint**. IAM (`container.clusters.connect`) governs it, and it is reachable through Private Google Access without IP allowlists.
- **Approved and adopted (2026-11-23):** clusters use the DNS-based endpoint with IP endpoints disabled. ArgoCD reaches them through Private Google Access, authenticated by IAM, so there is no authorized-network list. This must be tested with VPC-SC in Phase 1 of the rollout (decisions #22).

### V8. Certificate Manager limits
- Quotas per project: Google-managed certificates 1,000, self-managed 1,000, certificate maps 100, certificate map entries 5,000. Fixed limit: 4 certificates per map entry. Quotas can be raised.
- Demand in `compute-prod` at 500 customers is 500 managed certificates, about 1,000 map entries (2 per customer) and 1 map. Custom certificates are opt-in. Everything fits.
- **Design adjusted:** a wildcard `*.{customer}.platform.example` doesn't cover the apex `{customer}.platform.example`, which Decision 11 also serves. Each customer gets **one** Google-managed certificate with both SANs (apex and wildcard), DNS-authorized. It has two map entries: an apex hostname entry and a `*.` entry.
- UAT uses one wildcard certificate `*.uat.platform.example` in `compute-uat` (see architecture §10).

### V9. Cloud SQL cross-region DR and write endpoint
- Enterprise Plus **advanced DR** provides:
  - a designated cross-region DR replica
  - **switchover**: planned, no data loss, the primary goes read-only until the replica catches up
  - **replica failover**: unplanned, may lose the replication lag; the old primary rejoins as a replica when it returns
- The **write endpoint** is a global DNS name that resolves to the current primary and is repointed on switchover/failover.
- Requirements: Enterprise Plus, **private IP with private services access** (not PSC-only, not public-only), the **Cloud DNS API** enabled before the instance is created or promoted, matching SSL configuration on primary and replica, and the new network architecture. With Shared VPC, Service Networking and Compute APIs are enabled in both the host and the service project.
- **Design result:** matches Decision 10. L1 enables `dns.googleapis.com` in `data-prod` and `net-prod` before L2 creates instances. The spec's fallback (per-region connection config until cross-project resolution is tested) is kept and becomes a DR-test entry.
- Failover is per instance, so it is per cell (one instance per prod cell). This confirms Decision 10.

### V10. Cloud SQL import and role ownership (seed down)
- Before restoring a SQL dump, every user that owns objects or holds grants in the dump must exist in the target, or the import must run as a user that is a member of those roles (`gcloud sql import sql --user`). Plain imports don't support `--clean`; it only works with `--parallel`. To re-seed, drop and recreate the target database.
- **Confirms Decision 7:**
  - Step 4 (`NOLOGIN` role named after the target login, `REASSIGN OWNED`) makes the dump reference only the target login.
  - Step 6 recreates the target database (no `--clean`) and imports **as the target login**, which L3 already created as an IAM user.
- Related finding: `gcloud sql users create/assign-roles --database-roles=cloudsqlsuperuser` works for IAM users through the Admin API. The database bootstrap job's platform login (an IAM service account) gets `cloudsqlsuperuser` from Terraform via the Admin API. No built-in password user is needed, which keeps "Terraform never connects to a database" true.

### V11. VPC-SC: promotion reads, CMEK keys per perimeter
- A request from a client in one perimeter to a resource in another needs an **egress rule in the caller's perimeter** and an **ingress rule in the resource's perimeter**.
- Rule pair for image promotion:
  - prod perimeter **egress**: identity `promoter@platform-prod`, to project `platform-nonprod`, service `artifactregistry.googleapis.com`, read methods only
  - non-prod perimeter **ingress**: from identity `promoter@platform-prod`, to project `platform-nonprod`, service `artifactregistry.googleapis.com`, read methods only
  - Image copies for Compute Engine (Packer) use the same pair with `compute.googleapis.com` `images.get`/`images.insert` (source read only).
- CMEK keys never cross a perimeter: non-prod data uses `security-nonprod` keys, prod data uses `security-prod` keys, and exchange data uses keys in `data-exchange`. Signing keys follow the same rule. The promoter verifies the non-prod attestation using the public key exported to the prod perimeter as an attestor configuration, so no KMS call crosses the boundary.
- Dry-run caveat: Google notes copy-agent egress errors often appear only in dry-run mode, so the perimeters are enforced (not dry-run) before the first promotion is tested.

## Sources
- [IAM quotas and limits](https://docs.cloud.google.com/iam/quotas), [Create service accounts](https://docs.cloud.google.com/iam/docs/service-accounts-create)
- [Cloud Storage quotas](https://docs.cloud.google.com/storage/quotas), [About buckets](https://docs.cloud.google.com/storage/docs/buckets)
- [BigQuery quotas and limits](https://docs.cloud.google.com/bigquery/quotas), [Manage datasets (copy)](https://docs.cloud.google.com/bigquery/docs/managing-datasets), [Manage transfers](https://docs.cloud.google.com/bigquery/docs/working-with-transfers), [Cross-region replication](https://docs.cloud.google.com/bigquery/docs/data-replication)
- [Cloud Run quotas and limits](https://docs.cloud.google.com/run/quotas), [Cloud Run for multi-tenant platforms](https://docs.cloud.google.com/run/docs/securing/multi-tenant)
- [Cloud Storage CMEK](https://docs.cloud.google.com/storage/docs/encryption/customer-managed-keys), [CMEK best practices](https://docs.cloud.google.com/kms/docs/cmek-best-practices)
- [About Workload Identity Federation for GKE](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/workload-identity), [Identity federation: products and limitations](https://docs.cloud.google.com/iam/docs/federated-identity-supported-services)
- [GKE network isolation](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/network-isolation), [GKE hardening guide](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/hardening-your-cluster)
- [Certificate Manager quotas](https://docs.cloud.google.com/certificate-manager/docs/quotas), [Certificate map entries](https://docs.cloud.google.com/certificate-manager/docs/map-entries)
- [Cloud SQL advanced DR (PostgreSQL)](https://cloud.google.com/sql/docs/postgres/use-advanced-disaster-recovery), [Write endpoint](https://docs.cloud.google.com/sql/docs/mysql/connect-to-instance-using-write-endpoint), [Configure private services access](https://docs.cloud.google.com/sql/docs/postgres/configure-private-services-access)
- [Cloud SQL troubleshooting (import roles)](https://docs.cloud.google.com/sql/docs/postgres/troubleshooting), [gcloud sql import sql](https://docs.cloud.google.com/sdk/gcloud/reference/sql/import/sql), [Manage IAM database users](https://docs.cloud.google.com/sql/docs/postgres/add-manage-iam-users)
- [Artifact Registry with VPC-SC](https://cloud.google.com/artifact-registry/docs/securing-with-vpc-sc), [VPC-SC troubleshooting](https://docs.cloud.google.com/vpc-service-controls/docs/troubleshoot-services-within-perimeter)
