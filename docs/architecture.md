# Multi-Tenant GCP Platform: Architecture Design (D1)

| | |
|---|---|
| Status | Phase 1, for review |
| Scope | 15-20 products, 200+ customers (designed for 500+), 4 environments per customer, GKE / Cloud Run / Compute Engine MIGs |
| Companion documents | [decisions.md](decisions.md) (key decisions table), [gcp-verification.md](gcp-verification.md) (limits checked against Google docs), [diagrams/](diagrams/) |

## Document map

| Topic | Section | Diagram |
|---|---|---|
| Principles | [§1](#1-principles) | |
| Resource hierarchy, projects, VPC-SC | [§2](#2-resource-hierarchy-and-project-model) | [hierarchy.md](diagrams/hierarchy.md) |
| Regions, cells, placement, IP plan | [§3](#3-regions-cells-and-placement) | [regions.md](diagrams/regions.md) |
| Environment groups and clusters | [§4](#4-environment-groups-and-clusters) | [gke.md](diagrams/gke.md) |
| Runtime architectures (GKE, Cloud Run, MIG) | [§5](#5-runtime-architectures) | **[gke.md](diagrams/gke.md), [cloud-run.md](diagrams/cloud-run.md), [instance-group.md](diagrams/instance-group.md)** |
| Multi-product and multi-customer model | [§6](#6-multi-product-and-multi-customer-model) | [multi-product.md](diagrams/multi-product.md) |
| Version divergence and customization | [§7](#7-version-divergence-and-customization) | |
| Data architecture | [§8](#8-data-architecture) | [data.md](diagrams/data.md) |
| Data sharing between a customer's environments | [§9](#9-data-sharing-within-a-customer) | [data-sharing.md](diagrams/data-sharing.md) |
| Identity and encryption | [§10](#10-identity-and-encryption) | [network-security.md](diagrams/network-security.md) |
| Network, edge, mesh, zero trust | [§11](#11-network-edge-and-zero-trust) | [network-security.md](diagrams/network-security.md) |
| HA and DR | [§12](#12-ha-and-dr) | [ha-dr.md](diagrams/ha-dr.md) |
| Zero-downtime deployment | [§13](#13-zero-downtime-deployment) | |
| GitOps and ArgoCD | [§14](#14-gitops-and-argocd) | [gke.md](diagrams/gke.md) |
| Shared CI and Ansible runners | [§15](#15-shared-ci-and-ansible-runners) | [runners.md](diagrams/runners.md) |
| Labels and naming | [§16](#16-labels-and-naming) | |
| Execution model and Day 2 | [§17](#17-execution-model-and-day-2) | |
| Scale, quotas, cost | [§18](#18-scale-quotas-and-cost) | |
| Risks | [§19](#19-risks-and-mitigations) | |
| Clarifications of the brief | [§20](#20-clarifications-of-the-brief) | |
| **Scenario traceability** | [§21](#21-scenario-traceability) | |

## At a glance

- **About 12 fixed projects**, whatever the customer count. Regions and capacity cells are resources inside them.
- **Three environment groups per region:** Dev/Stage, UAT and Prod, each with its own clusters, exposure and upgrade channel. Prod has a dedicated DR cluster in the region's DR pair.
- **Onboarding input is one field**, `region.primary`. A Git-only placement job picks the clusters and Cloud SQL instances for each environment group and writes them back to `customer.yaml`.
- **Pool infrastructure, not data.**
  - Shared: clusters and Cloud SQL instances.
  - Per customer: namespace, database (one schema per product), buckets, datasets, topics, KMS keys and identities.
- **Three one-way, audited data flows** inside a customer: shared reference, promote up, seed down (sanitized).
- **Every prod customer gets HA and DR:** zone failure is automatic; region failure is a warm standby with RTO ~30 min and RPO ~5 min.
- **Terraform manages GCP (L0-L3) and ArgoCD manages Kubernetes (L4).** Git is the registry for regions, cells and placements.

---

## 1. Principles

| Principle | What it means in practice |
|---|---|
| Environment is the compute boundary | Clusters, Shared VPCs, exposure, ArgoCD instances and runner pools are split by environment group. Non-prod tooling has no network path or identity into prod. |
| Customer is the data and identity boundary | Everything a customer owns carries `customer=<id>`, lives in per-customer containers, and is encrypted with a per-customer key. It can be listed, moved, backed up and deleted as a unit. |
| Pool infrastructure, not data | Customers share clusters and Cloud SQL instances. Each customer gets its own namespace, database, bucket, dataset and topic inside them. |
| Data never moves implicitly | The only cross-environment movement is through the three named flows in §9. |
| Stateless by default | MIGs have no data disks. GKE PVCs are an approved, catalog-declared exception for rebuildable data only. |
| Terraform for GCP, ArgoCD for Kubernetes | Terraform installs only ArgoCD into clusters and never connects to a database. Database grants are applied by the bootstrap job. |
| Git is the registry | Regions, clusters, SQL instances and placements are YAML files in Git. Automation reads Git and never queries GCP to make a decision, so the logic is testable offline. |

## 2. Resource hierarchy and project model

Diagram: [hierarchy.md](diagrams/hierarchy.md).

```
Organization
└── Folder: Platform
    ├── Network   → net-nonprod, net-prod                     (Shared VPC hosts)
    ├── Compute   → compute-devstage, compute-uat, compute-prod
    ├── Data      → data-nonprod, data-prod, data-exchange
    ├── Platform  → platform-nonprod, platform-prod
    ├── Security  → security-nonprod, security-prod
    └── Dedicated-Customers → {customer}/{customer}-dedicated  (only isolation: dedicated)
```

| Project | Perimeter | Shared VPC | Holds |
|---|---|---|---|
| `net-nonprod` | non-prod | host | Global VPC `vpc-nonprod`, subnets per region, Cloud Routers, Cloud NAT, private DNS zones |
| `net-prod` | prod | host | Global VPC `vpc-prod`, subnets per region, Cloud Routers, Cloud NAT (static IPs), public DNS zone |
| `compute-devstage` | non-prod | service of `net-nonprod` | Dev/Stage clusters, Cloud Run, MIGs, regional internal ALBs, customer dev/stage GSAs |
| `compute-uat` | non-prod | service of `net-nonprod` | UAT clusters, Cloud Run, MIGs, UAT global external ALB, Cloud Armor, UAT certificate, customer UAT GSAs |
| `compute-prod` | prod | service of `net-prod` | Prod clusters, dedicated DR clusters, Cloud Run, MIGs (primary + DR), prod global external ALB, Cloud Armor, Certificate Manager, customer prod GSAs |
| `data-nonprod` | non-prod | service of `net-nonprod` | Non-prod Cloud SQL instances, dev/stage/uat buckets, datasets, topics, bootstrap job, seed import job |
| `data-prod` | prod | service of `net-prod` | Prod Cloud SQL (with cross-region DR replicas), prod buckets, datasets, topics, bootstrap job, seed-down scheduler + function + scratch instances |
| `data-exchange` | exchange | none (API access only) | Per customer: shared bucket, shared dataset, seed bucket, and the exchange key ring |
| `platform-nonprod` | non-prod | service of `net-nonprod` | Management cluster (ArgoCD Dev/Stage + UAT), non-prod runner pools, non-prod Artifact Registry, non-prod Packer image family |
| `platform-prod` | prod | service of `net-prod` | Management cluster (ArgoCD Prod), prod runner pools, prod Artifact Registry (multi-region, promoted only), prod image family, Cloud Monitoring metrics scope |
| `security-nonprod` | non-prod | none | Per-customer non-prod key rings, build attestor and signing key, CAS private CA |
| `security-prod` | prod | none | Per-customer prod key rings, prod attestor and signing key, central log sink buckets, SCC configuration |

- **IaC seed project:** L0 creates `<prefix>-iac-seed`, outside the 12, holding only the Terraform state bucket, the Terraform service accounts and the CI identity federation pool.
- **Fixed count:** 12 projects for 200 or 500 customers. Dedicated projects are added only for `isolation: dedicated`. A shared project is added only when a documented quota or regulatory trigger fires (see [gcp-verification.md](gcp-verification.md) V1 and V3).
- **Project factory** (L1 Terraform module): creates every project with labels, a billing link, a budget (50/80/100%), a log sink, essential contacts and org-policy defaults. It runs as a dedicated service account that has Project Creator only on the Platform and Dedicated-Customers folders.
- **Org policies** (on the Platform folder):
  - `gcp.resourceLocations` = approved regions and their multi-regions
  - `compute.vmExternalIpAccess` = deny
  - `iam.disableServiceAccountKeyCreation`
  - `compute.requireOsLogin`, `compute.requireShieldedVm`
  - `compute.trustedImageProjects` = `platform-nonprod`, `platform-prod`
  - `storage.uniformBucketLevelAccess`, `storage.publicAccessPrevention`
  - `sql.restrictPublicIp`, `run.allowedIngress` = `internal-and-cloud-load-balancing`
  - `gcp.restrictNonCmekServices` for storage, BigQuery and compute
- **IAM model:** groups and service accounts only. Customer identities never hold project-level roles, apart from two allowlisted exceptions that can't be granted on a single resource:
  - `roles/cloudsql.client` and `roles/cloudsql.instanceUser` on the data project, with an IAM condition on the customer's instance name
  - `roles/logging.logWriter` and `roles/monitoring.metricWriter` for MIG GSAs

  The static policy check (`policy/`) fails any other project-level grant to a customer identity.

### VPC Service Controls

Three perimeters, enforced (dry-run only until the self-hosted runners are live in L1):

| Perimeter | Projects |
|---|---|
| non-prod | `net-nonprod`, `compute-devstage`, `compute-uat`, `data-nonprod`, `platform-nonprod`, `security-nonprod` |
| prod | `net-prod`, `compute-prod`, `data-prod`, `platform-prod`, `security-prod` |
| exchange | `data-exchange` |

| From → to | Identity | Allowed (ingress/egress rule pair) |
|---|---|---|
| prod → exchange | prod customer GSAs (and KSA principals) | read the customer's shared bucket/dataset |
| prod → exchange | `seed-publisher@data-prod`, scratch-instance Cloud SQL service agent | write seed bucket objects |
| prod → exchange | `promoter@platform-prod` (prod pool) | write shared reference, after approval |
| non-prod → exchange | non-prod customer GSAs (and KSA principals) | read the customer's shared bucket/dataset |
| non-prod → exchange | `seed-import@data-nonprod`, non-prod Cloud SQL service agent | read seed bucket objects |
| prod → non-prod | `promoter@platform-prod` | Artifact Registry read and `compute.images.get` on `platform-nonprod` only |
| non-prod → prod | anyone | nothing |
| prod → non-prod, exchange | `tf-l1` (L1 foundation, prod pool, extra approval) | administration |
| prod → exchange | `tf-prod` (per-customer exchange states) | administration of `data-exchange` |
| anything else | anyone | denied |

The rules are implemented in `infrastructure/layers/L1-foundation` (module `vpc-sc`). The two
administration rows were added in Phase 2: L1 runs on the prod pool, and the exchange states have
to manage the exchange perimeter from somewhere.

CMEK keys live in the perimeter of the data they protect: `security-nonprod`, `security-prod`, and `data-exchange` for exchange data. Keys never cross a perimeter.

## 3. Regions, cells and placement

Diagram: [regions.md](diagrams/regions.md).

### Region inventory
`inventory/regions.yaml` lists every supported region:
- `status: reserved | active`
- its DR pair in the same jurisdiction (`us-east1 ↔ us-central1`, `europe-west1 ↔ europe-west4`)
- its IP plan
- region quotas used by placement

A prod region can't be `active` without its pair. Adding a region is an approved platform PR. L2 then builds the region's footprint in every project.

### Cells
A cell is one cluster plus the Cloud SQL instance(s) that serve its customers. Cells are recorded by L2 in `inventory/clusters/*.yaml` and `inventory/sql/*.yaml`.

| Cell resource | Cap (starting, tunable per cell in inventory) |
|---|---|
| Dev/Stage cluster | 40 customers |
| UAT cluster | 40 customers |
| Prod cluster | 25 customers |
| Non-prod Cloud SQL instance | 40 customers (dev, stage and uat databases) |
| Prod Cloud SQL instance | 25 customers, exactly one per prod cell |

### Placement job
`scripts/placement/` runs in GitHub Actions on every customer PR. It reads only Git.

1. Validates `customer.yaml`: the ID format, and that `region.primary` is `active` (otherwise it fails with "region not provisioned").
2. For each environment group, picks the cell in `region.primary` with the most free headroom (`capacity.maxCustomers − assigned`) among cells with `status: active`.
3. **Aligns databases with clusters:**
   - non-prod databases go on a non-prod instance in the same region
   - the prod database goes on **the instance of the chosen prod cell**, so the prod DB, its DR replica, the prod cluster and the DR cluster always line up
4. **Checks region quotas** (added by verification V3): it projects the Cloud Run service count per project per region, and for prod also in the DR pair region, against `quotas.cloudRunServices`.
5. Writes `placement.*` back to `customer.yaml` as a bot commit. Existing placements are never changed by the job; moving a customer is an explicit runbook.
6. With no headroom, it opens a **capacity PR** (new cell, `status: provisioning`) and fails the customer PR until L2 marks the cell `active`.

Because the job is a pure function of the repo, it is unit-tested offline in CI.

### IP address plan
Each region gets one `/16` per side (`cidr` in `regions.yaml`) and one `/13` per side for pods and services (`podCidr`, from `100.64.0.0/10`), so pods don't consume the region `/16`. No hybrid connectivity exists, so non-RFC1918 pod ranges never leak.

Every cluster has a **slot** (0-23) per region per side, recorded in `regions.yaml`, and gets its own subnet (decisions #23). Slot 0 is reserved for the management cluster.

| Range (computed with `cidrsubnet`) | Use |
|---|---|
| `cidrsubnet(cidr, 8, slot)` → `/24` in `x.x.0.0/19` | `snet-<cluster>`: node range of that cluster (≤ 250 nodes) |
| `cidrsubnet(podCidr, 5, slot)` → `/18` | pod secondary range (64 pods/node → `/25` per node → 128 nodes) |
| `cidrsubnet(cidrsubnet(podCidr, 2, 3), 7, slot)` → `/22` | service secondary range (1,024 services) |
| `x.x.32.0/20` | `snet-run-<region>`: Cloud Run Direct VPC egress |
| `x.x.48.0/22` | `snet-mig-<region>`: MIG instances |
| `x.x.52.0/23` | Proxy-only subnet (regional internal ALB) |
| `x.x.54.0/24` | `snet-ops-<region>`: Ansible runners |
| `x.x.64.0/18` | Private services access allocation (Cloud SQL) |
| `x.x.128.0/17` | Reserved |

| `podCidr` per region per side | non-prod | prod |
|---|---|---|
| `us-east1` | `100.64.0.0/13` | `100.96.0.0/13` |
| `us-central1` | `100.72.0.0/13` | `100.104.0.0/13` |
| `europe-west1` | `100.80.0.0/13` | `100.112.0.0/13` |
| `europe-west4` | `100.88.0.0/13` | `100.120.0.0/13` |

- **Capacity:** 23 clusters per region per side. On the prod side these slots are shared between the region's own prod cells and the DR clusters of its pair, which gives up to ~11 prod cells (~275 prod customers) per region.
- **Beyond four regions:** further regions use the class E range `240.0.0.0/4`, which GKE supports for pods.
- `podCidr` and the slots extend the reference format (§20).

## 4. Environment groups and clusters

| Group | Environments | Exposure | Release channel | Cluster |
|---|---|---|---|---|
| Dev/Stage | dev, stage | Private: regional internal ALB, operators via IAP | RAPID | Zonal control plane, node pools in 3 zones |
| UAT | uat | Global external ALB, Cloud Armor IP allowlist | REGULAR | Regional |
| Prod | prod | Global external ALB, Cloud Armor | STABLE | Regional (3 zones) + dedicated DR cluster `<cluster>-dr` in the pair region |

- **Cluster names:** `{group}-{region}-{nn}`, for example `devstage-us-east1-01`, `uat-us-east1-01`, `prod-us-east1-01` and `prod-us-east1-01-dr` (located in `us-central1`).
- **Common cluster configuration:**
  - private nodes; control plane reachable only through the **DNS-based endpoint** (IP endpoints disabled), authorized by IAM `container.clusters.connect` (decisions #22)
  - Dataplane V2, Workload Identity Federation, Shielded Nodes, Binary Authorization enforced, managed Istio (Cloud Service Mesh)
  - Backup for GKE agent, Security Posture, Cloud Logging/Monitoring with Managed Prometheus
  - node auto-upgrade with maintenance windows and exclusions
- **Upgrades** flow Dev/Stage → UAT → Prod with 2-4 weeks of validation, enforced by the channel choice plus maintenance exclusions on Prod.
- **Isolation between one customer's non-prod environments** (dev and stage share a cluster; dev, stage and uat share a SQL instance):
  - separate namespaces with default-deny NetworkPolicies, an Istio AuthorizationPolicy and Sidecar scoping
  - separate databases with `CONNECT` granted only to that environment's login
  - separate GSAs and KSAs, and separate buckets, datasets and topics
- Cloud Run services and MIGs follow the same groups. They are created per customer, per product, per environment, in the matching compute project and in the customer's region.

## 5. Runtime architectures

The three required diagrams (D2) show the full topology for each runtime: **[GKE](diagrams/gke.md)**, **[Cloud Run](diagrams/cloud-run.md)** and **[Instance Group](diagrams/instance-group.md)**, each with an exported SVG next to it.

| Concern | GKE | Cloud Run | MIG |
|---|---|---|---|
| Unit per customer | Namespace `{customer}-{env}` (tenant chart) + product Releases | Service `{customer}-{product}-{env}` | Regional MIG `{customer}-{product}-{env}` |
| Tenant boundary | Namespace, NetworkPolicy, Istio AuthZ + Sidecar, AppProject, ResourceQuota | Separate service, runs as the customer env GSA, invoker IAM per service | Separate MIG and instance template, runs as the customer env GSA, per-tenant network tag + firewall |
| Prod ingress | Cloud Armor → global ALB → Cloud CDN → Istio ingress gateway (NEG) | Cloud Armor → global ALB → serverless NEG → service (`internal-and-cloud-load-balancing`) | Cloud Armor → global ALB → backend service → regional MIG |
| Egress | Istio egress gateway + NetworkPolicy + firewall → Cloud NAT static IPs | Direct VPC egress (all traffic) → firewall → Cloud NAT | Firewall by tag → Cloud NAT |
| Identity to Google APIs | KSA principal via WIF; impersonates the env GSA for Cloud SQL | Env GSA | Env GSA |
| Deploy path (L4) | ArgoCD ApplicationSets (tenant + product charts), Argo Rollouts canary | Pipeline step: new revision with no traffic → staged split | Packer image → promotion → new instance template → rolling update; Ansible for config + migrations |
| Schema migration | ArgoCD PreSync hook Job | Cloud Run job before the traffic shift | Ansible task before the rolling update |
| DR copy | Dedicated DR cluster at minimum replicas | Same service in the pair region behind the same LB | MIG in the pair region at minimum size |

**Who owns what (Cloud Run and MIG):** L3 Terraform creates the service, MIG and instance template, with identity, labels, networking and scaling bounds. The L4 delivery step owns the version: Terraform ignores the image/revision/template version, and the deploy step changes it. This matches GKE, where Terraform never touches workloads.

## 6. Multi-product and multi-customer model

Diagram: [multi-product.md](diagrams/multi-product.md).

- **Catalog (platform-owned):** `products/<product>/product.yaml` declares:
  - runtime and short code
  - data services (Cloud SQL schema, bucket, dataset, Pub/Sub publish/subscribe)
  - an optional persistent volume (GKE only, approved)
  - sizing per environment, dependencies, networking (egress allowlist, ports) and compliance flags
- **Customer selection:** `customers/<customer>/products.yaml` lists enabled products, the version per product per environment, overrides and product config.
- **Composition rules** (enforced by the PR validator and the L3 composition module):
  - Per enabled product, per environment, the customer gets the product's schema in the customer's database, plus its own bucket, dataset and topics, **only if the catalog requires them**.
  - Pub/Sub subscriptions are valid only for Cloud Run products. Publishers may be GKE or Cloud Run. MIG products neither publish nor subscribe in this version.
  - Persistent volumes are valid only for approved GKE products.
  - Merge: the largest size wins, resources are unioned, customer overrides are applied last.
  - Dependencies must be enabled in the same environment, and the version window is respected.
- **Same infrastructure, many products:** all of a customer's products in one environment share its namespace (GKE), its env GSA, its database and its KMS key, and each keeps its own schema, bucket, dataset, topics, Deployment/service/MIG and Helm release.
- **What one customer gets** (exactly this is created on onboarding and deleted on offboarding):
  - 4 namespaces across 3 clusters (+ prod also on the DR cluster), or the matching Cloud Run services and MIGs
  - 4 databases (`{customer}_{env}`, hyphens → underscores), one schema per enabled product, reached through the env login
  - per enabled product per environment: a bucket, a dataset and topics as the catalog requires (plus the prod DR dataset)
  - in `data-exchange`: one shared bucket, one shared dataset, one seed bucket, and the exchange key ring
  - a KMS key ring per environment group in the required locations
  - 4 env GSAs, an ArgoCD AppProject, Backup for GKE plans and data-sharing grants
  - 3 files in Git: `customer.yaml`, `products.yaml`, `data-sharing.yaml`
- **Day 2:** see §17.

## 7. Version divergence and customization

1. **One codebase per product, immutable artifacts.** Images are referenced by tag and pinned to a digest at promotion. Versions are pinned per customer per environment in `products.yaml`:
   ```yaml
   products:
     payment-api:
       versions: { dev: 2.6.0-beta.1, stage: 2.5.1, uat: 2.5.1, prod: 2.5.0 }
       config: { currency: USD }
   ```
2. **Customization, in order of preference:**
   1. configuration values (Helm values layering `base → product → environment → customer`, Cloud Run env, Ansible vars)
   2. feature flags (shared reference flow)
   3. product extension points
   4. **variant images** (`payment-api:2.5.0-acme-corp.1`) built from `customer-variants/<customer>/` in the product repo, only when `variantImages: true`

   Forks are rejected.
3. **Support window:** latest N, N-1 and N-2 minor versions. The validator rejects pins outside the window.
4. **Schema compatibility:** each product schema migrates independently per customer with expand/contract. `product.yaml` declares `schemaCompatibility` (the oldest app version compatible with the current schema). Breaking changes use blue-green, sequenced per customer.
5. **Version matrix:** CI generates customer × product × environment × version from `customers/*/products.yaml` and publishes it as a build artifact and a docs page.
6. **Environment skew:** dev may run newer or beta versions. The version-compatibility guard (§9) blocks data flows between incompatible versions.
7. **Rollout waves:** a new version is rolled out by bot-generated pin PRs in batches (canary customers → 10% → 50% → all). Each batch waits for the previous batch's SLO checks.

## 8. Data architecture

Diagram: [data.md](diagrams/data.md).

| Service | Per customer | Location | Isolation mechanism |
|---|---|---|---|
| Cloud SQL for PostgreSQL | One database per env (`acme_corp_prod`) on pooled instances, one schema per product | Customer's region. Prod: Enterprise Plus, regional HA, cross-region DR replica, write endpoint | `CONNECT` only for the env login (bootstrap job); `PUBLIC` revoked |
| GCS | One bucket per customer × product × env | Non-prod regional. Prod configurable dual-region (primary + pair) with turbo replication | Bucket IAM (uniform), customer CMEK |
| BigQuery | One dataset per customer × product × env, plus prod DR dataset | Customer's region; prod daily copy to the pair region | Dataset IAM, customer CMEK; no row-level security |
| Pub/Sub | Topics/subscriptions per customer × product × env | Message storage policy = region + pair | Topic/subscription IAM, CMEK, DLQ + retry, OIDC push |

**Cloud SQL login and bootstrap**
- **Logins:** one IAM service-account user per customer per environment (`acme-corp-prod@<compute-prod>.iam`), created by L3 through the Cloud SQL Admin API.
- **Bootstrap login:** the database bootstrap job runs as an IAM login (`db-bootstrap@data-*`) that holds `cloudsqlsuperuser`, assigned through the Admin API (verification V10). No password user exists.
- **Database bootstrap job:** a platform-owned Cloud Run job in `data-nonprod` / `data-prod`, run by the pipeline right after L3 apply. It is idempotent. For each customer database it:
  1. `REVOKE CONNECT, TEMP ON DATABASE … FROM PUBLIC`; `REVOKE ALL ON SCHEMA public FROM PUBLIC`
  2. `GRANT CONNECT, TEMP` to the env login only
  3. `CREATE SCHEMA IF NOT EXISTS <product> AUTHORIZATION <env login>` for each enabled product
  4. writes a `_platform_bootstrap` marker with a hash of the grant set. A release gate fails when a database has no current marker (this addresses the "database left with PUBLIC access" risk).
- **Migrations:** product migration jobs create and migrate objects inside their schema. Schemas are separated by convention between one customer's products, because the products share the env login. Isolation **between customers** is enforced by `CONNECT`.
- **Heavy products:** may get a dedicated product instance by catalog exception. It still holds one database per customer per environment.

**Persistent storage**
- MIGs are fully stateless.
- GKE PVCs (approved catalog exception, rebuildable data only):
  - RWO PD; regional PD in prod, zonal in non-prod
  - a per-customer StorageClass `sc-{customer}-{env}` with the customer CMEK and labels
  - quota on storage and PVC count
  - `Retain` in prod, `Delete` in dev
  - StatefulSets with ≥ 2 replicas and partitioned updates
  - Backup for GKE plan per customer namespace, prod backups stored in the pair region
- No Filestore. Shared files go to GCS, mounted read-only with the GCS FUSE CSI driver or `gcsfuse`.

**Not offered:** Memorystore, Cloud Tasks, Cloud Scheduler (as a product service), Filestore. Cloud KMS, Secret Manager and the seed-down scheduler/functions are platform-owned.

## 9. Data sharing within a customer

Diagram: [data-sharing.md](diagrams/data-sharing.md). There are no live cross-environment connections, and no path between customers.

| Flow | Direction | Mechanism | Who writes / who reads |
|---|---|---|---|
| Shared reference | all 4 envs read | Customer's shared bucket + dataset in `data-exchange` | Written only by the promote pipeline (prod pool, after approval). Read by every env GSA/KSA of that customer. Mountable read-only. |
| Promote up | dev → stage → uat → prod | Versioned export packages (config-as-code in Git, or product export/import API) | Pipeline with an approval per step (`data-sharing.yaml`). Lower envs never write into prod. |
| Seed down | prod → uat/stage/dev | Cloud SQL export → scratch instance → sanitize → verify → export to the exchange seed bucket → non-prod import. BigQuery: scheduled anonymizing query to the exchange. GCS: Storage Transfer Service with excluded prefixes. | The prod side publishes. The non-prod side pulls. No prod identity writes into non-prod. |

**Cloud SQL seed down** (one run covers all of a customer's products):
1. The scheduler or an on-demand trigger starts the orchestrating Cloud Function (`data-prod`).
2. It exports `acme_corp_prod` (native export, serverless) to a work bucket in `data-prod`.
3. It imports the export into a temporary scratch instance in `data-prod`, inside the prod perimeter and in the same region.
4. It runs `sanitize.sql`, then `verify.sql`, and writes `_clone_metadata`. A verification failure alerts and stops the flow.
5. **Role mapping:** it creates a `NOLOGIN` role named after the target login (`acme-corp-uat@<compute-uat>.iam`) and runs `REASSIGN OWNED BY <prod login> TO <target role>`.
6. It exports the sanitized database to `pfx-acme-corp-seed` in `data-exchange`, then deletes the scratch instance.
7. The non-prod import job (`data-nonprod`, non-prod identity) reads the dump, drops and recreates `acme_corp_uat`, imports it **as the target login**, and reruns the bootstrap job for that database.

- **Policy:** `customers/<c>/data-sharing.yaml` (`sharedReference`, `promoteUp.approvals`, `seedDown.targets/mode/schedule`). Terraform turns it into the IAM grants, and the isolation tests assert them.
- **Mandatory sanitization:**
  - auth secrets: hashes, salts, MFA, backup codes, recovery keys, security questions
  - all session and token tables truncated
  - API keys replaced with `TEST_`-prefixed keys; webhook/OAuth secrets regenerated; third-party tokens nulled
  - payment tokens, card fingerprints and provider IDs replaced
  - PII anonymized (email, phone, name, address, national ID)
- **Version-compatibility guard:** the source and target product versions must be inside each schema's declared compatibility window.
- **Excluded:** PVCs and Pub/Sub messages.

## 10. Identity and encryption

Diagram: [network-security.md](diagrams/network-security.md).

**Identities**

| Identity | Where | Used by |
|---|---|---|
| `{customer}-{env}` GSA | compute project of the env group | Cloud SQL login (all runtimes); runtime identity of Cloud Run services and MIGs; impersonated by GKE pods for Cloud SQL and signed URLs |
| KSA `{product}` in `{customer}-{env}` | cluster (tenant chart) | GKE pods; granted IAM directly via WIF principal for GCS, BigQuery, Pub/Sub, KMS, Secret Manager |
| Platform SAs | `platform-*`, `data-*` | runners per pool, promoter, ArgoCD, bootstrap job, seed publisher/importer, Terraform per layer |

- Resource-level IAM only (plus the two allowlisted conditional grants). Tokens last ≤ 1 h. No service-account keys (org policy). No credential is shared across customers or environments.
- **Database access:** `CONNECT` per env login. GKE pods connect through the Cloud SQL Auth Proxy sidecar (or the language connector) with `--auto-iam-authn`, impersonating the env GSA.

**Encryption**

| Data | Key |
|---|---|
| GCS, BigQuery, PD (incl. Backup for GKE) | Customer key ring in `security-nonprod` (Dev/Stage + UAT groups) or `security-prod` (prod) |
| Exchange data | Customer key ring in `data-exchange` |
| Pooled Cloud SQL instance | Platform key per instance. Sensitive columns use **application envelope encryption with the customer's key** (shared platform library), so destroying the customer key crypto-shreds them. `isolation: dedicated` gets an instance key. |

- **Key ring locations:**
  - non-prod: the customer's region
  - prod: region + pair region + multi-region (`us`/`eu`) for dual-region buckets (verification V5)
- Key rings are named `kr-{customer}-{group}`. Keys are `{env}-data` (GCS/BQ/PD/Pub/Sub) and `{env}-app` (envelope), with 90-day rotation.
- **Offboarding:** disable then destroy the customer's keys after the retention period, which crypto-shreds everything they protect.

## 11. Network, edge and zero trust

**Network**
- Two global Shared VPCs (`vpc-nonprod`, `vpc-prod`), never peered, with subnets per region (§3 IP plan).
- Private Google Access and PSC for Google APIs. Cloud Router + Cloud NAT per region (prod uses static IPs, published to customers for allowlisting).
- Firewall:
  - hierarchical policy at the Platform folder: deny ingress from the internet except GFE/health-check ranges; allow IAP (`35.235.240.0/20`) to tcp/22 only for the ops tag
  - VPC firewall rules for cluster, MIG and runner tags

**Edge**

| Group | Path | Hostnames | Certificates |
|---|---|---|---|
| Dev/Stage | Operator → IAP → regional internal ALB → Istio ingress / serverless NEG / MIG | `{customer}.{env}.platform.internal` (private zone) | CAS private CA |
| UAT | Internet → Cloud Armor (IP allowlist) → global external ALB | `{customer}.uat.platform.example` (public zone) | One Certificate Manager wildcard `*.uat.platform.example` |
| Prod | Internet → Cloud Armor → global external ALB → per-customer host rule → primary region backends (DR on failover) | `{customer}.platform.example`, `api.{customer}.platform.example`; custom domains via CNAME | One Certificate Manager cert per customer (apex + wildcard, DNS authorization) in a certificate map; customer certs when `edge.customCertificate` |

- **Cloud Armor:** DDoS, OWASP CRS, geo-blocking, bot management, rate limits per client IP and per customer (keyed on `Host`).
- **API authentication without a gateway:**
  - GKE: Istio `RequestAuthentication` (JWT) + `AuthorizationPolicy` requiring the `customer` claim to match the host
  - Cloud Run and MIG: a shared platform JWT library
  - IAP for operator and internal access
- **API versioning:** path-based (`/v1/`, `/v2/`) in the URL map and Istio VirtualServices.
- Apigee is out of scope and can be inserted between the LB and the backends later.

**Service mesh and per-runtime isolation**
- **GKE:**
  - managed Istio, `PeerAuthentication` STRICT, AuthorizationPolicy + Sidecar per namespace
  - default-deny egress (NetworkPolicy + Istio `REGISTRY_ONLY` + firewall), ServiceEntry allowlist, egress gateway, Cloud NAT
- **Cloud Run and MIG (no mesh):**
  - per-service identity (the env GSA) and invoker bindings
  - Cloud Run: ingress `internal-and-cloud-load-balancing`, Direct VPC egress with `all-traffic`, and firewall rules on the Cloud Run network tag `t-{customer}-{env}`
  - MIG: tag `t-{customer}-{env}`, with rules allowing only LB/health-check ranges in and Ansible runners on 22. No tag can reach another tenant's tag.
  - TLS from the LB to the backend.
  - The weaker native boundary is mitigated by default-deny firewall per tag, identity-scoped data access and the isolation tests (§19).

**Zero trust controls**

| Layer | Control |
|---|---|
| Identity | §10 |
| Network | mTLS (GKE), default deny, VPC-SC, private clusters, PGA, allowlisted egress |
| Workload | Binary Authorization on GKE and Cloud Run (non-prod attestor in non-prod, prod attestor added at promotion), break-glass documented. Shielded VM + trusted image projects for MIGs. AR scanning blocks CRITICAL/HIGH. Pod Security Standards `restricted`. Shielded GKE nodes. |
| Data | Per-customer keys, TLS 1.2+, DLP scanning of buckets/datasets, application-level encryption for PII |
| Monitoring | SCC, Audit Logs → central sink (BigQuery + SIEM export), Falco on GKE, alerting, automated remediation, pen tests |

## 12. HA and DR

Diagram: [ha-dr.md](diagrams/ha-dr.md).

| Component | HA (zone failure, automatic) | DR (region failure, warm standby in the pair) |
|---|---|---|
| GKE | Regional cluster, 3 zones, PDBs, topology spread | Dedicated DR cluster `<cell>-dr` at minimum size. The prod ArgoCD deploys every prod app there at minimum replicas and scales up on failover. |
| Cloud SQL | Regional HA | Enterprise Plus advanced DR replica (same size as the primary), failover/switchover, write endpoint |
| Cloud Run | Multi-zone | Same service in the pair region, second serverless NEG in the same backend service |
| MIG | Regional MIG, 3 zones, autohealing | MIG in the pair region at minimum size, scaled on failover |
| GCS | n/a | Dual-region + turbo replication (RPO ≤ 15 min) |
| BigQuery | n/a | Daily cross-region copy (RPO 24 h), not part of failover |
| Pub/Sub | Global | Storage policy = pair; push subscriptions re-pointed to the DR Cloud Run |
| PVCs | Regional PD | Backup for GKE in the pair region, restored on failover |
| Edge | LB health checks | DR backends are attached to the same backend services with capacity 0. Failover sets `drActive: true` for the cell in `regions.yaml`, and the edge/L3 apply shifts capacity to DR (decisions #25). |
| Supporting | n/a | Secrets replicated to the pair; prod AR multi-region; KMS in both regions; ArgoCD Prod rebuildable in the pair from Git |

| Profile | RTO | RPO |
|---|---|---|
| Zone failure | ~1-5 min | 0 |
| **Region failure, warm standby (default)** | **~30 min** | **~5 min** |
| Region failure, `dr: hot-standby` | ~5 min | ~1 min |
| Non-prod (backup/restore) | 4 h | 24 h |

- **Failover is per cell:** one prod Cloud SQL instance per cell, so one failover moves exactly one cell's customers. DR clusters are dedicated, so failover never doubles load on another cell.
- **Runbook (failover):**
  1. Declare; freeze deploys to the cell.
  2. `promote-replica --failover` on the cell's instance.
  3. Confirm the write endpoint resolves to the new primary (fallback: switch the per-region connection config).
  4. Scale the DR cluster, MIGs and Cloud Run min instances.
  5. Shift the LB backends: a PR setting `drActive: true` for the cell, applied by the prod pool.
  6. Re-point push subscriptions.
  7. Verify SLOs.

  **Failback:** a switchover (no data loss) after the region returns.
- **Backups:** Cloud SQL daily (30 days) + PITR (7 days); Backup for GKE daily (14 days); GCS versioning + soft delete. Failover tests run quarterly per cell.
- **Cost:** prod Cloud SQL replicas are sized like the primaries, and DR clusters and MIGs run at minimum. This roughly **doubles the fixed prod database footprint per region** and adds ~15-25% to prod compute. It is the accepted price of default DR.

## 13. Zero-downtime deployment

| Runtime | Default | Progressive | Major / breaking |
|---|---|---|---|
| GKE stateless | RollingUpdate 25%/25%, PDB, probes `/healthz/ready` + `/healthz/live`, preStop 15 s | Argo Rollouts canary 10→25→50→100 with Istio traffic split + AnalysisTemplate (error rate, p95 latency), automatic rollback | Blue-green Rollout |
| GKE stateful (approved PVC) | StatefulSet, partitioned rolling update, one pod at a time, ≥ 2 replicas | n/a | Manual partition steps |
| Cloud Run | New revision with `--no-traffic` and a tag | Traffic 10→25→50→100 with health/SLO check between steps, automatic rollback to the previous revision; min instances in prod | Blue-green via tags |
| MIG | Rolling update `maxUnavailable=0`, `maxSurge` ≥ 3 (one per zone), autohealing, connection draining | Canary via a second version in the rolling update (`--canary-version target-size=10%`) | Blue-green: second MIG on the same backend service, then the weight is shifted |

Schema migrations run before the new version takes traffic, and follow expand/contract:
- GKE: ArgoCD PreSync hook Job
- Cloud Run: Cloud Run job
- MIG: Ansible task

## 14. GitOps and ArgoCD

- **Three instances:** Dev/Stage and UAT on the `platform-nonprod` management cluster, Prod on the `platform-prod` management cluster. Each instance holds credentials only for its group's clusters.
- **Cluster access (decisions #22):**
  - ArgoCD reaches each cluster's **DNS-based control-plane endpoint** through Private Google Access. IAM (`roles/container.admin` for that group's ArgoCD service account on that group's compute project only) authorizes it, through Workload Identity with `argocd-k8s-auth gcp`.
  - No stored kubeconfigs and no authorized-network lists.
  - L2 records each cluster's DNS endpoint in `inventory/clusters/*.yaml`, and an ArgoCD app renders the credential-free cluster Secrets from it.
  - Connect Gateway is for operators only.
- **App-of-apps per instance:** L1 installs ArgoCD together with one root Application (C17). The root Application deploys `argocd/root`, using that instance's values and the generated `argocd/generated/<group>/root.yaml`. The root renders:
  - credential-free cluster Secrets, built from the inventory
  - the AppProjects
  - one ApplicationSet per platform add-on. The add-ons are cert-manager, Argo Rollouts, Falco, `mesh` (ingress and egress gateways, mesh-wide STRICT mTLS, JWT checks at the edge) and `platform` (canary analysis template, label admission policy, Istio metrics, Managed Prometheus query frontend).
  - the tenant ApplicationSet and the product ApplicationSet
- **GitOps index (C18):** a single ApplicationSet generator cannot join the customer, the catalog, the version pins and the cell inventory. `scripts/render-gitops.py` does that join and writes one small file per Application under `argocd/generated/<group>/`:
  - the file holds the ApplicationSet parameters (`argocd:` block)
  - the same file is that Application's last, platform-owned Helm values layer
  - it runs after placement, and CI fails if it is out of date (`--check`)
  - it also checks each version pin against the support window, the variant-image opt-in, and that prod has no pre-releases
- **Tenant ApplicationSet:** Git files generator over `argocd/generated/<group>/tenants/*.yaml`. It creates one Application per customer, per environment, per target cluster (in prod, both the primary cluster and the DR cluster), deploying `helm/tenant` into the platform-owned `platform-tenants` AppProject.
- **Product ApplicationSet:** Git files generator over `argocd/generated/<group>/products/*.yaml`. It creates one Application per customer × GKE product × environment × target cluster, deploying `helm/product-base` into the customer's AppProject.
  - The value files are applied in this order: chart base → `products/<p>/helm/values.yaml` → `values-<env>.yaml` → `customers/<c>/helm/<p>/values[-<env>].yaml` (optional) → generated platform values. Because the generated layer comes last, identity, version pin, sizing, data names, hosts and egress cannot be overridden.
  - The DR copy runs at minimum replicas. It stays at full size for hot standby or once the cell's `drActive` is set. It runs no migrations and uses plain rolling updates.
- **AppProjects (C19):**
  - `platform-addons` is the only project allowed cluster-wide resources.
  - `platform-tenants` may create Namespaces, StorageClasses and the guardrails (quota, LimitRange, NetworkPolicy, Sidecar, PeerAuthentication, RequestAuthentication, AuthorizationPolicy, ServiceAccount), only in customer namespaces.
  - Each customer gets one project for its product Applications. It is limited to that customer's namespaces on its placed clusters (including the DR cluster) and to an allowlist of namespaced workload and routing kinds. It has no cluster-scoped resources and cannot touch the guardrails.
- **Safety:**
  - In Prod, every ApplicationSet uses `applicationsSync: create-update` and `preserveResourcesOnDeletion: true`. The Prod controller also sets this as its instance-wide policy, and the Prod root Application never prunes. Deletion only happens through phased decommission.
  - Prod product syncs run in an allow window (Mon–Thu 14:00–20:00 UTC). A manual sync is still possible outside it, as break-glass.
  - Tenant namespaces and StorageClasses in prod carry `Delete=false`.
  - `manifest-generate-paths` limits a refresh to the Applications whose chart, value files or index file changed.
- **Scale:** controller sharding, repo-server replicas, Redis HA, webhooks instead of polling. Escape hatch: split an instance by region (the generators already filter by placement).
- **Rebuild:** Git holds all desired state. The runbook covers rebuilding the Prod instance in the pair region.

## 15. Shared CI and Ansible runners

Diagram: [runners.md](diagrams/runners.md).

| Pool | Project | Runs |
|---|---|---|
| GitHub Actions (non-prod) | `platform-nonprod` (ARC on the management cluster) | L2/L3 non-prod Terraform, placement commit, image builds for GitHub products, Packer builds |
| GitHub Actions (prod) | `platform-prod` (ARC) | L1 (extra approval), L2/L3 prod Terraform, image promotion, Cloud Run/MIG prod deploy steps |
| Bitbucket Pipelines (non-prod) | `platform-nonprod` (Bitbucket runner on k8s) | Build, scan and sign for Bitbucket products, push to the non-prod AR |
| Ansible (non-prod / prod) | `platform-*` (small MIG, OS Login, IAP-only SSH) | MIG configuration and migrations, dynamic inventory by labels |

- All runners are ephemeral, one job each, with no public IP, egress through Cloud NAT, and GCP auth via WIF (GitHub OIDC, Bitbucket OIDC). The non-prod pool identity has no role on prod projects, and vice versa.
- **Image promotion:** builds push to the non-prod AR and are signed with the non-prod key. The prod promoter:
  1. verifies the non-prod attestation
  2. copies **by digest** into the prod AR
  3. adds a prod attestation (prod key in `security-prod`)

  Prod Binary Authorization requires the prod attestation. Packer images follow the same path into the prod image family.
- Runners sit inside the VPC-SC perimeters, which is why Terraform runs on them. Fork PRs on the public repo never reach them (GitHub Environments + `pull_request` from forks on GitHub-hosted runners with no secrets).

## 16. Labels and naming

**Mandatory labels** on every labelable GCP resource, and as Kubernetes labels on every namespace and workload:

| Label | Values |
|---|---|
| `customer` | customer ID, or `shared` |
| `environment` | `dev`, `stage`, `uat`, `prod` (or `shared`) |
| `env-group` | `devstage`, `uat`, `prod` (or `shared`) |
| `product` | short code, or `platform` |
| `region-role` | `primary`, `dr` |
| `managed-by` | `terraform`, `argocd` |

Every Terraform module takes a `labels` input built by a shared `locals` helper and merges it into every resource. A static check fails any module or chart that misses a key. Labels are for identification, operations, audits and offboarding. Customers are billed by subscription, so there is no per-customer cost engine. The billing export shows platform spend per project, group, region and product.

**Naming**

| Resource | Pattern | Example |
|---|---|---|
| Customer ID | `^[a-z][a-z0-9-]{1,18}[a-z0-9]$` (≤ 20) | `acme-corp` |
| Product short code | ≤ 12 | `payment` |
| Namespace | `{customer}-{env}` | `acme-corp-prod` |
| Cloud Run service, MIG | `{customer}-{product}-{env}` | `acme-corp-reporting-prod` |
| Customer GSA | `{customer}-{env}` | `acme-corp-prod@<compute-prod>.iam.gserviceaccount.com` |
| GCS bucket | `{prefix}-{customer}-{product}-{env}` | `pfx-acme-corp-reporting-prod` |
| Exchange buckets | `{prefix}-{customer}-shared`, `{prefix}-{customer}-seed` | `pfx-acme-corp-shared` |
| BigQuery dataset | `{customer}_{product}_{env}` (hyphens → `_`) | `acme_corp_reporting_prod` |
| Cloud SQL database / schema | `{customer}_{env}` / `{product}` | `acme_corp_prod` / `reporting` |
| Pub/Sub topic | `{customer}-{product}-{env}-{name}` | `acme-corp-payment-prod-events` |
| Cluster | `{group}-{region}-{nn}[-dr]` | `prod-us-east1-01-dr` |
| SQL instance | `sql-{nonprod|prod}-{region}-{nn}[-dr]` | `sql-prod-us-east1-01` |
| Key ring | `kr-{customer}-{group}` | `kr-acme-corp-prod` |

## 17. Execution model and Day 2

| Layer | Creates | Tool / runs on | State |
|---|---|---|---|
| L0 Bootstrap | TF service accounts per layer, state bucket, GitHub + Bitbucket WIF, top folders | Script, laptop, once | local → GCS |
| L1 Foundation | Fixed projects (factory), APIs, Shared VPCs, VPC-SC, org policies, ARs, security baselines, runner pools, management clusters, 3 ArgoCD instances, quota requests | Terraform, GitHub-hosted first apply, then prod pool | 1 |
| L2 Region | Subnets, routers, NAT, group clusters + DR cluster, SQL instances + DR replicas, exchange regional resources, KMS locations, LB backends; writes `inventory/clusters|sql` | Terraform on the group's pool; ArgoCD installs add-ons | 1 per region per group |
| L3 Customer | Databases + IAM DB users, buckets, datasets, topics, keys, GSAs + IAM, Cloud Run + MIG definitions, Backup plans, data-sharing grants (dedicated project if opted in) | Terraform on the group's pool, then the bootstrap job | 1 per customer per env, plus `keys-nonprod`, `keys-prod`, `exchange` (decisions #24) |
| L2 Edge | Load balancers, Cloud Armor, certificates and DNS per group, built from Git (C14) | Terraform on the group's pool | 1 per group (Dev/Stage: per region) |
| L4 Delivery | Tenant chart, workloads, migrations, version rollouts | ArgoCD, Cloud Run deploy step, Packer + Ansible | none (Git) |

- **Rules:**
  - L3 reads names from `inventory/`, never hard-coded.
  - Changed-path detection means a customer PR plans only that customer's states.
  - Scheduled drift plans run per state in batches and alert on diff.
  - Project factory guardrails apply (§2).
- **State layout:** `gs://<state-bucket>/L3/<customer>/<env>`. At 500 customers that is 2,000 small L3 states. It is fast to plan, isolates blast radius, and parallelizes. Terragrunt is not used: the plain per-directory layout is generated from a template by a script, and the composition module carries the logic.
- **Onboarding** (target < 30 min from merge):
  1. PR with `customer.yaml` (region only), `products.yaml` and `data-sharing.yaml`
  2. Validation + placement (bot commit)
  3. Merge
  4. L3 apply for 4 envs in parallel, ~10 min
  5. Bootstrap job, ~1 min
  6. ArgoCD tenant + product sync / Cloud Run deploy / MIG rollout, ~10 min
  7. Smoke tests and isolation sample
- **Add a product** (< 20 min): PR to `products.yaml` → validator (dependencies, window, runtime rules) → the plan summary is commented → merge → L3 adds the schema, bucket, dataset and topics → bootstrap → ArgoCD / deploy.
- **Remove a product:** phased decommission.
  1. Disable traffic.
  2. Scale to zero.
  3. Retention period (data kept, IAM revoked).
  4. Approvals from `platform-admin` and `customer-success`.
  5. Drop the schema, delete the bucket, dataset and topics.

  Other products are untouched.
- **Upgrade:** a version pin PR, done by rollout waves (§7).

## 18. Scale, quotas and cost

| Item | 200 customers | 500 customers | Handling |
|---|---|---|---|
| Projects | 12 | 12 (+ dedicated, + quota-trigger projects) | Fixed model |
| Prod clusters (+ DR) | 8 (+8) | 20 (+20) | Cells, 25 per cell |
| Dev/Stage + UAT clusters | 5 + 5 | 13 + 13 | Cells, 40 per cell |
| Prod SQL instances (+ replicas) | 8 (+8) | 20 (+20) | One per prod cell |
| GSAs per compute project | ≤ 400 | ≤ 1,000 | Quota increase (V1) |
| Buckets / datasets | ~4,000 each | ~10,000 each | No count limit; create rate respected (V2) |
| Cloud Run services per project-region | up to ~800 | up to ~2,000 | Quota tracked by placement; trigger project (V3) |
| Certificates / map entries (prod) | 200 / 400 | 500 / 1,000 | Under quota (V8) |
| ArgoCD Applications (prod instance) | ~2,000 (×2 with DR) | ~5,000 (×2) | Sharding; split by region if needed |
| L3 states | 800 | 2,000 | Changed-path planning, batched drift |

Cost levers:
- pooled clusters and instances
- provision only what the product selection needs
- Dev/Stage merged into one group
- DR at minimum size
- committed-use discounts on the fixed footprint
- regions added only by approval

Platform cost grows per cell (every 25 to 40 customers), not per customer.

## 19. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Terraform state at scale | Per-customer-per-env states, changed-path planning, batched drift |
| Helm values sprawl | Four fixed layers (base, product, env, customer), JSON schema per layer, CI render for every customer |
| Cost explosion, DR footprint | Cells, minimum-size DR, budgets per project, quarterly right-sizing from load tests |
| Shared-cell blast radius | Caps per cell, one SQL instance per prod cell, per-cell failover, upgrade waves per cell |
| RBAC complexity | AppProject per customer generated from Git; groups only; static IAM checks |
| Tenant-context bug leaking data | Data containers per customer (DB, bucket, dataset), so a bug can't reach another customer's data with its credentials; JWT customer claim checked at Istio; isolation tests |
| Drift | Scheduled plans, ArgoCD self-heal, `managed-by` label |
| Onboarding bottleneck | One-field PR, automatic placement, < 30 min pipeline |
| Version matrix, schema migrations | Support window, compatibility metadata, validator, waves |
| Istio overhead | Managed control plane, Sidecar scoping, right-sized proxies |
| Canary metric quality | AnalysisTemplates per product from SLOs, minimum request counts before judging |
| Replica lag, endpoint switch | Same-size replicas, lag alerting, write endpoint + fallback config, quarterly tests |
| Binary Authorization friction | Same signing path for GitHub and Bitbucket, break-glass with audit |
| Sanitization failure | Mandatory verification gate, `_clone_metadata`, stop on failure |
| Seed-down role mapping | `NOLOGIN` target role + `REASSIGN OWNED`, import as target login (V10) |
| DB left with PUBLIC access | Bootstrap marker + release gate + isolation tests |
| Promote-up depends on product export/import | Catalog flag `supportsExport`; products without it can't enable promote-up |
| Object counts and quotas | Verification V1-V3, V8; placement checks quotas |
| Bucket name uniqueness | Platform prefix + customer + product + env, validated at PR |
| IP planning | `/16` per region per side, pods from `100.64.0.0/10` (§3) |
| ArgoCD scale | Sharding, split by region |
| VPC-SC rules across perimeters | Explicit rule table (§2), dry-run first, enforced before promotion tests |
| Catalog drift | Catalog schema in CI; customer PRs validated against the current catalog |
| Accidental product removal | Phased decommission, retention, two approvals, Prod ApplicationSets never delete |
| Public repo exposure | Fake IDs, secret scan, no secrets or self-hosted runners for forks |
| Cloud Run/MIG weaker isolation | Per-tenant identity, per-tag firewall, invoker IAM, isolation tests cover them |
| Cloud Run quota per project-region | Placement quota check; trigger project (V3) |

## 20. Clarifications of the brief

These resolve inconsistencies or gaps in the brief. None of them changes a locked decision.

| # | Topic | Resolution |
|---|---|---|
| C1 | Name examples used `acme-` and `acme_corp_` inconsistently | All names use the full customer ID: `acme-corp-prod`, `acme_corp_prod`. Hyphens become underscores where GCP or PostgreSQL disallow them. |
| C2 | Dev/Stage "VPN/IAP" vs "no hybrid connectivity" | Operator access is IAP only (IAP for HTTPS on the internal ALB, IAP TCP forwarding). No Cloud VPN. |
| C3 | Seed-down components had no project | Scheduler, orchestrating function, work bucket and scratch instances in `data-prod`; import job in `data-nonprod`. |
| C4 | Helm 3 vs local Helm 4 | Charts use `apiVersion: v2` (Helm 3 compatible); CI pins Helm 3. |
| C5 | UAT is exposed on an external LB but non-prod DNS was private only | UAT uses public `{customer}.uat.platform.example` with one wildcard certificate in `compute-uat`. Dev/stage stay private (`.platform.internal`). |
| C6 | `*.{customer}.platform.example` doesn't cover the apex | One managed certificate per customer with the apex and the wildcard SANs (V8). |
| C7 | Seed dumps need a write target separate from shared reference | A per-customer seed bucket `{prefix}-{customer}-seed` in `data-exchange`, 7-day lifecycle. |
| C8 | Trusted image project for MIGs was not named | `platform-nonprod` (non-prod image family) and `platform-prod` (promoted family) via `compute.trustedImageProjects`. |
| C9 | Pod IP ranges would exhaust the region /16 | Pods use `100.64.0.0/10` (`podCidr` added to `regions.yaml`). |
| C10 | Cloud Run "per-service identity" vs "env GSA is the Cloud Run identity" | Each service runs as the customer env GSA (per customer, per env). Invoker bindings are per service. |
| C11 | Version ownership for Cloud Run and MIG between L3 and L4 | Terraform owns the shape and ignores the version; the L4 deploy step owns the revision/template version. |
| C12 | Cloud Run quota | Quota tracked in inventory and checked by placement (V3). |
| C13 | The cell inventory is "written by L2" but something must declare which cells to build | The capacity PR edits `regions.yaml` (`cells.*` with slot numbers and caps). L2 builds those cells and writes `inventory/clusters|sql/*.yaml`, which placement reads. |
| C14 | One global LB URL map can't be owned by 200 customer states | `L2-edge/{devstage-<region>,uat,prod}` states own everything on the LB, built from Git: backend services (Istio gateway NEGs, Cloud Run serverless NEGs, MIGs, referenced by deterministic names), host rules, Cloud Armor, certificates, map entries and DNS records. L2/L3 create only the NEGs and MIGs. Order: edge (initial) → L3 → edge (host rules). |
| C15 | Per-group key rings and exchange resources span env states | Per-customer `keys-nonprod`, `keys-prod` and `exchange` states (decisions #24). |
| C16 | Non-prod Cloud SQL instances aren't tied to a cluster | Non-prod instances are a regional pool declared in `regions.yaml` (`sqlInstances.nonprod`), created by the Dev/Stage L2 state. All of a customer's dev/stage/uat databases go on one non-prod instance in its region. |
| C17 | Terraform installs ArgoCD into the management clusters | The only Terraform-to-cluster connection (L1, Helm provider, DNS endpoint). L2/L3 never connect to a cluster. The ArgoCD release includes the root Application (`extraObjects`); everything after that comes from Git. |
| C18 | The brief has ApplicationSets generate Applications straight from `customer.yaml` and `products.yaml` | Generators cannot join the customer, the catalog and the inventory. `scripts/render-gitops.py` writes a generated index (one file per Application, which is also its last values layer), and the ApplicationSets read only that index. CI checks it is current, as it does for the Terraform roots (decisions #26). |
| C19 | The brief says the tenant ApplicationSet "generates the customer's AppProject" | An ApplicationSet creates Applications, not AppProjects. The root chart renders the per-customer AppProjects from the same index. Tenant Applications run in a platform-owned project, because the tenant chart creates cluster-scoped objects (Namespace, StorageClass) that a customer project must not be allowed to create. |
| C20 | Who holds the canary metrics, the egress routes and the gateway TLS | Canary analysis reads Istio metrics from Managed Prometheus through a query frontend, authorized by a Workload Identity principal (L1 IAM). Egress is split: the product chart owns the sidecar-to-gateway leg and the mesh add-on owns the gateway-to-host leg for the catalog's allowlist. LB-to-gateway TLS uses a cert-manager certificate (the external ALB does not validate backend certificates). |

## 21. Scenario traceability

| Scenario item / deliverable | Satisfied by |
|---|---|
| S1. Four environments per customer (dev, stage, uat, prod) | §4 environment groups; §6 namespaces/databases per env; §17 L3 state per env |
| S2. 15-20 products | §6 catalog (`products/*/product.yaml`), composition rules; [multi-product.md](diagrams/multi-product.md) |
| S3. Runtimes: GKE, Cloud Run, Instance Groups | §5 runtime table; D2 diagrams; §13 per-runtime rollouts |
| S4. 200+ customers | §3 cells + placement; §18 scale table; [gcp-verification.md](gcp-verification.md) |
| S5. Several products per customer in the same infrastructure/project | §2 fixed projects; §6 "same infrastructure, many products"; §8 one database with a schema per product |
| S6. Version divergence with customer-specific customization | §7; §14 product ApplicationSets with per-customer pins |
| S7. Data sharing between a customer's own environments | §9 three flows; §2 VPC-SC exchange rules; [data-sharing.md](diagrams/data-sharing.md) |
| S8. Shared infrastructure: GitHub/Bitbucket and Ansible runners | §15; [runners.md](diagrams/runners.md) |
| Brief deliverable 1: architecture design (4 envs, multi-product/customer, version divergence, data sharing) | This document (§4, §6, §7, §9) + [decisions.md](decisions.md) |
| Brief deliverable 2: three diagrams (Cloud Run, GKE, Instance Group) | [diagrams/cloud-run.md](diagrams/cloud-run.md), [diagrams/gke.md](diagrams/gke.md), [diagrams/instance-group.md](diagrams/instance-group.md) + `.svg` |
| Brief deliverable 3: Terraform | `infrastructure/` (Phase 2), layers in §17 |
| Brief deliverable 4: Helm charts for GKE | `helm/tenant`, `helm/product-base`, `argocd/` (§14); rendered output in `examples/rendered/` |
| Brief deliverable 5: public repository | Repo layout + CI (Phase 4); push only on request |
| D1 Architecture design + decisions + traceability | This document, [decisions.md](decisions.md), §21 |
| D2 Three runtime diagrams (Mermaid + SVG) | `docs/diagrams/{gke,cloud-run,instance-group}.{md,svg}` |
| D3 Terraform L0-L3, two example customers, fmt/validate/test | Phase 2 |
| D4 Tenant + product base charts, lint/template/schema | `scripts/gitops-check.py`: helm lint, ApplicationSet expansion, helm template, kubeconform, manifest policy |
| D5 Public repo, README, CI, no secrets | Phase 4 |
| Goal: region-only onboarding | §3 placement |
| Goal: prod HA/DR by default | §12 |
| Goal: fixed project count | §2, §18 |
| Goal: labels identify customer/product/env | §16 |
| Goal: zero trust, zero downtime | §11, §13 |
| Goal: Day 2 without disruption | §17 |
| Goal: 5-engineer operability | §17 automation, §14 GitOps, §3 placement, §18 |
