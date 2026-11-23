# Multi-Tenant GCP Platform

## Project brief

Design a multi-tenant, multi-product GCP infrastructure for four environments, then prove it with architecture diagrams, Terraform and Helm charts pushed to a public repository.

**Scenario:** A software company runs 15 to 20 products on Google Cloud and serves 200+ customers. Design the infrastructure and automation that hosts all of them.

1. **Environments:** four per customer: dev, stage, uat and prod.
2. **Products:** 15 to 20 different products.
3. **Runtimes:** products are deployed on GKE, Cloud Run or Instance Groups.
4. **Customers:** 200+ customers.
5. **Multi-product tenancy:** one customer can run several products inside the same infrastructure/project.
6. **Version divergence:** different customers can run the same product at different versions, with customer-specific customizations.
7. **Data sharing:** a customer's data can be shared between that customer's own environments.
8. **Shared infrastructure:** GitHub/Bitbucket and Ansible runners.

**Deliverables:**

1. GCP infrastructure architecture design covering the four environments, the multi-product and multi-customer model, version divergence and data sharing.
2. Three separate architecture diagrams: one each for Cloud Run, GKE and Instance Group deployments.
3. Terraform scripts for infrastructure automation.
4. Helm charts for GKE deployment.
5. Documentation and code pushed to a public GitHub or Bitbucket repository, with the link shared for review.

The rest of this prompt defines how to deliver this brief. The architecture decisions below are agreed and locked.

## Role
You are a Senior DevOps Architect hired to design and build the cloud infrastructure for our multi-tenant SaaS platform. You collaborate with platform engineering, product teams, security and SRE. You deliver working artifacts (diagrams, Terraform, Helm) in a public Git repository, not only a design document.

## Goal
Design and implement a multi-tenant GCP platform that:

- Hosts 15-20 products for 200+ customers, each with four environments (dev, stage, uat, prod)
- Onboards a customer from a single input, the **region** they want to run in, with no sizing questions
- Lets customers run the same product at different versions with customer-specific customizations
- Keeps every customer's data strictly isolated from other customers, while letting a customer share data between its own environments through explicit, audited flows
- Standardizes deployment across **GKE, Cloud Run and Compute Engine Instance Groups**
- Provides shared CI and Ansible runner infrastructure for GitHub and Bitbucket
- Gives **every prod customer HA and DR by default**
- Keeps the number of GCP projects fixed as customers grow
- Labels every resource so its customer, product and environment can be identified at a glance (customers are billed by product subscription, so per-customer cost attribution is not needed)
- Implements zero trust with defense in depth and zero-downtime deployments on all three runtimes
- Supports Day 2 add/remove/upgrade of products without disruption
- Scales operationally without linear team growth (5 engineers)

## Deliverables (definition of done)

| # | Deliverable | Definition of done |
|---|---|---|
| D1 | Architecture design document | Covers the 4 environments, the multi-product and multi-customer model, version divergence, data sharing, shared runners, regions and HA/DR, with a decisions table and a **scenario traceability table** (each scenario item and deliverable → the design section that satisfies it) |
| D2 | **Three separate architecture diagrams**: GKE, Cloud Run, Instance Group | One diagram per runtime in its own file, as Mermaid source **and an exported SVG**, each showing topology, tenant isolation, ingress/egress, identity, deploy path, and the DR copy for prod |
| D3 | Terraform | Modules organized by layer (L0-L3; L4 is delivery through ArgoCD, the Cloud Run deploy step and Packer/Ansible, with no Terraform) and two example customers. `terraform fmt -check`, `terraform validate` and `terraform test` (with mock providers) pass with no credentials |
| D4 | Helm charts for GKE | A product base chart and a tenant chart, with product, environment and customer values layering. `helm lint`, `helm template` and schema validation pass for the example customers |
| D5 | Public repository | Everything above is pushed to a **public GitHub repository** with README, CI and no secrets or real identifiers (see "Public repository constraints"). The repository URL is provided in the final checklist for review. |

Supporting diagrams (resource hierarchy, data architecture, data-sharing flows, network/security, HA/DR, multi-product composition, region model, runner topology) are required but secondary. They must not crowd out D2 to D4.

## Context

**Business context**
- B2B SaaS company, 200+ enterprise customers, greenfield (no migration)
- Each customer has 4 environments: dev, stage, uat, prod
- 15-20 products. Runtime mapping:
  - Containerized microservices → GKE
  - Stateless HTTP APIs and event-driven services → Cloud Run
  - Legacy or VM-based workloads → Compute Engine managed instance groups (MIGs)
- Customers subscribe to different product combinations, and the selection changes over time (Day 2)
- Customers are billed by product subscription price, not by the cloud cost of their resources
- User counts, data volumes and SLAs per customer are **not known in advance**

**Current tooling**
- GitHub and GitHub Actions. The platform configuration repo, `platform-config`, is also the public deliverable repo for this project.
- Bitbucket for some product application repos. Their builds run on Bitbucket Pipelines using the shared self-hosted runners (Decision 17), and ArgoCD reads them through repo credentials.
- ArgoCD (GitOps), Argo Rollouts, Istio (managed), Ansible (VM configuration), Packer (golden images), Artifact Registry, Secret Manager, Cloud KMS, Certificate Manager

## Architecture decisions (locked in)

### 1. Principles
- **Environment is the compute boundary.** Clusters, networks, exposure and access are split by environment group.
- **Customer is the data and identity boundary.** Everything a customer owns can be listed, moved, backed up and deleted as a unit.
- **Pool infrastructure, not data.** Customers share clusters and database instances, but each customer has its own containers inside them (namespace, database, bucket, dataset, topic).
- **Data never moves between environments implicitly.** All sharing goes through named, one-way, audited flows (Decision 7).
- **Stateless by default.** Persistent disks are an approved exception, never the default.
- **Terraform manages GCP, ArgoCD manages Kubernetes.** Terraform never writes objects into a cluster except installing ArgoCD itself. Terraform never connects to a database; it uses only Google APIs.
- **Git is the registry.** What exists (regions, clusters, database instances) and where each customer lives are recorded in Git. Automation reads Git, never queries GCP to make decisions.

### 2. Environment groups and clusters
Each region has three environment groups. Each group has its own clusters, exposure and upgrade channel.

| Group | Environments | Exposure | GKE release channel | Cluster type |
|---|---|---|---|---|
| Dev/Stage | dev, stage | Private only: regional internal Application LB, reached via VPN/IAP | RAPID (dev-first validation) | Zonal control plane, node pools across 3 zones |
| UAT | uat | Global external LB with a Cloud Armor IP allowlist | REGULAR | Regional |
| Prod | prod | Global external LB behind Cloud Armor | STABLE | Regional, 3 zones, plus a dedicated DR cluster in the pair region |

- **Dev and stage intentionally share a group.** They have the same exposure, certificates and upgrade channel, so separate clusters would add a cluster per region and another ArgoCD instance with little gain.
- **Isolation between a customer's non-prod environments.** Dev and stage share a cluster, and dev, stage and uat share the non-prod Cloud SQL instance. Separation between them relies on:
  - separate namespaces (`acme-dev`, `acme-stage`) with default-deny NetworkPolicies and Istio AuthorizationPolicy
  - separate databases (`acme_dev`, `acme_stage`, `acme_uat`), with `CONNECT` granted only to that environment's roles
  - separate identities and Kubernetes service accounts per environment
  - separate buckets, datasets and topics per environment
  This is isolation between one customer's own environments. Isolation between customers is unchanged (Decision 8).
- Cluster upgrades flow Dev/Stage → UAT → Prod, with 2-4 weeks of validation before prod.
- Private clusters with no public endpoint.
- GKE namespaces: `{customer}-{env}` (e.g. `acme-dev`, `acme-stage`, `acme-uat`, `acme-prod`).
- Cloud Run services and MIGs follow the same grouping. They are created per customer, per product, per environment, in the matching compute project and in the customer's region.

### 3. Regions and placement (no sizing tiers)
- **The only onboarding input is `region.primary`** in `customer.yaml`. Do not introduce sizing tiers (such as Small/Medium/Large): user counts, data volumes and SLAs are not known up front.
- Supported regions are listed in `inventory/regions.yaml` with a status (`reserved | active`), their IP ranges, and a **DR pair region in the same jurisdiction**. A customer PR naming a region that is not `active` fails with "region not provisioned".
- **Adding a region requires an approved platform-team PR**, because every region has a fixed running cost. L2 Terraform then creates the region's footprint in every project (see "Execution model"). A prod region cannot become `active` without its DR pair.
- **A cell** is a unit of capacity inside a region: a cluster plus the Cloud SQL instance(s) that serve the customers on it. Cells live inside the fixed projects. Adding a cell adds clusters and instances, never projects.
- **Placement job** (a script run by GitHub Actions, not Terraform) runs on every new customer PR:
  1. Reads `inventory/` and every `customers/*/customer.yaml`.
  2. For each environment group, picks the cell in `region.primary` with the most free headroom against its capacity cap.
  3. **Aligns the databases with the clusters:** every database for the customer is placed on a Cloud SQL instance **in the same region** as the customer's clusters. For prod, the database goes on the instance that belongs to the chosen prod cell, so the prod database, its cross-region replica, the prod cluster and its DR cluster always line up.
  4. Commits the assignments back to `customer.yaml` (`placement.*`). Humans never hand-pick clusters or instances.
- The placement job only reads Git, so it is unit-tested offline in CI.
- **Capacity caps (starting values, tunable):**

  | Resource | Cap |
  |---|---|
  | Dev/Stage cluster | 40 customers |
  | UAT cluster | 40 customers |
  | Prod cluster | 25 customers |
  | Non-prod Cloud SQL instance | 40 customers |
  | Prod Cloud SQL instance | 25 customers. One instance per prod cell, never shared between cells. |

  Caps are stored per cell in `inventory/` (`capacity.*`), so changing one is a PR, not a code change. Refine them from load tests during the MVP.
- If a region has no headroom, the job opens a **capacity PR** (new cell) for the platform team to approve and fails the customer PR until the cell is `active`.
- Customer data never leaves its region and DR pair. An org policy (`gcp.resourceLocations`) limits every project to the approved regions.
- **Opt-in options, set explicitly per customer and approved at contract time:**
  - `isolation: dedicated`: dedicated project, cluster and database instance (created by the project factory)
  - `dr: hot-standby`: DR cluster kept at full size for a lower RTO (Decision 10)
  - `edge.customCertificate` / `edge.customDomain`: customer-provided certificate and CNAME domain
  - `variantImages: true`: allows customer variant images (see "Version divergence")

### 4. Project model (fixed project set)
The number of projects does **not** grow with customers or regions. Regions and cells are resources inside these projects.

| Project | Holds |
|---|---|
| `net-nonprod` / `net-prod` | Shared VPC hosts (one global VPC each, subnets per region), Cloud Routers, Cloud NAT |
| `compute-devstage` | Dev/Stage GKE clusters, Cloud Run services, MIGs, regional internal LBs (all regions) |
| `compute-uat` | UAT GKE clusters, Cloud Run services, MIGs, the UAT global external LB, Cloud Armor policies, certificates |
| `compute-prod` | Prod and DR GKE clusters, Cloud Run services, MIGs, the prod global external LB, Cloud Armor policies, Certificate Manager |
| `data-nonprod` | Cloud SQL instances, buckets, BigQuery datasets and Pub/Sub topics for dev, stage and uat |
| `data-prod` | The same for prod, including cross-region replicas |
| `data-exchange` | Per-customer shared reference data and sanitized data published from prod (Decision 7) |
| `platform-nonprod` | Management GKE cluster with the Dev/Stage and UAT ArgoCD instances, non-prod runner pools (Decision 17), non-prod Artifact Registry (build target) |
| `platform-prod` | Management GKE cluster with the Prod ArgoCD instance, prod runner pools, prod Artifact Registry (promoted images only), Cloud Monitoring metrics scope |
| `security-nonprod` | Non-prod per-customer KMS key rings, build attestor and signing key |
| `security-prod` | Prod per-customer KMS key rings, prod attestor and signing key, central log sinks, Security Command Center |

- About 12 fixed projects for 200 or 500 customers. Dedicated-customer projects are added only for `isolation: dedicated`.
- `platform-nonprod` and `platform-prod` are service projects of `net-nonprod` and `net-prod` respectively, so non-prod tooling has no network path into prod.
- Add a shared project only when a trigger fires (a project-wide quota is close to its limit, or a regulator requires separation). Most compute quotas are per project per region, so adding regions adds headroom.
- **VPC Service Controls:** a non-prod perimeter (`net-nonprod`, `compute-devstage`, `compute-uat`, `data-nonprod`, `platform-nonprod`, `security-nonprod`), a prod perimeter (`net-prod`, `compute-prod`, `data-prod`, `platform-prod`, `security-prod`) and an exchange perimeter (`data-exchange`). Cross-perimeter access is limited to the rules in the table below. Everything else is denied. CMEK keys must sit inside the same perimeter as the data they protect, so each perimeter holds its own keys (`security-nonprod`, `security-prod`, and `data-exchange` for exchange data). Keys never cross a perimeter. Container images cross from non-prod to prod only through image promotion (Decision 17): the prod promotion identity reads from the non-prod registry, and no non-prod identity can write into the prod perimeter.

  | From → to | Who | Allowed |
  |---|---|---|
  | prod → exchange | Prod workloads | Read their customer's shared reference only |
  | prod → exchange | Seed-down publisher | Write seed dumps only |
  | prod → exchange | Promote pipeline (prod pool) | Write shared reference only, after approval |
  | non-prod → exchange | Non-prod workloads | Read their customer's shared reference |
  | non-prod → exchange | Non-prod import job and the Cloud SQL service agent | Read seed dumps |
  | prod → non-prod | Prod promotion identity | Read the non-prod Artifact Registry only |
  | non-prod → prod | Anyone | Nothing |
  | Anything else | Anyone | Denied |
- All projects are created by the **project factory** Terraform module (labels, billing link, budget, log sink, org-policy defaults).
- IAM in every project is granted to groups and service accounts. **Customer identities never get project-level roles.** Two exceptions exist, because these roles cannot be granted on a single resource: `roles/cloudsql.client` and `roles/cloudsql.instanceUser` are granted at project level **with an IAM condition limited to the customer's Cloud SQL instance**, and MIG service accounts get `roles/logging.logWriter` and `roles/monitoring.metricWriter`. The static policy check allowlists exactly these and fails anything else.

### 5. Data services (the product catalog's only data options)

| Service | Per customer | Location | Notes |
|---|---|---|---|
| **Cloud SQL for PostgreSQL** | **One database per customer per environment** (`acme_dev` … `acme_prod`) on pooled instances, with **one schema per enabled product** inside it | Customer's region. Prod pools use Enterprise Plus with a cross-region DR replica (advanced DR, write endpoint). | Login is one IAM service account per customer per environment (Cloud SQL IAM users must be users, service accounts or groups). Between one customer's products, schemas are separated by convention, not enforced, because they share that login. Databases and IAM database users are created by Terraform through the Cloud SQL Admin API. The database bootstrap job (below) applies grants and creates the product schemas. Each product's migration job creates and migrates the objects inside its schema. Native per-database export/import gives simple seed down, restore, move and offboarding. |
| **GCS** | **One bucket per customer × product × environment**, plus one shared bucket per customer in the exchange | Regional for non-prod. **Dual-region (primary + DR pair) with turbo replication** for prod. | Bucket-level IAM and key, simple to audit, clean product removal |
| **BigQuery** | **One dataset per customer × product × environment**, plus one shared dataset per customer in the exchange | Customer's region. Prod gets a daily cross-region copy to the DR pair (RPO 24 h). BigQuery holds analytics, not system-of-record data. | Per-dataset IAM and key. No reliance on row-level security for isolation. |
| **Pub/Sub** | Topics and subscriptions **per customer, per product, per environment** | Message storage restricted to the customer's region and DR pair | **Cloud Run products subscribe. GKE and Cloud Run products may publish.** Push or Eventarc delivery to internal-only Cloud Run, OIDC-authenticated. Dead-letter topic and retry policy required. Consumers must be idempotent (at-least-once delivery). |

- **Database bootstrap job:** a platform-owned Cloud Run job in the data project of each environment side, run by the pipeline right after L3 apply (not by Terraform). For each customer database it revokes `CONNECT` and `TEMP` from `PUBLIC`, grants `CONNECT` only to the customer's environment login, and pre-creates the product schemas owned by that login. It is idempotent and runs as a platform admin login. Product migration jobs then create and migrate the objects inside their schema.
- **Exception for heavy products:** a product that needs its own engine, version or instance size may get a **dedicated product instance** (still one database per customer per environment on it). This is a catalog exception, not the default.
- **Not offered in the catalog:** Redis (Memorystore), Cloud Tasks, Cloud Scheduler, Filestore. A product that needs a cache or queue uses in-process caching or Cloud SQL for now. Adding a service later is a catalog change, not a redesign.
- **Platform-owned, not requestable by products:** Cloud KMS, Secret Manager, and the Cloud Scheduler + Cloud Functions that run the seed-down flow.

### 6. Persistent storage
- **MIGs are fully stateless.** No persistent data disks. Packer images hold code, Ansible holds configuration, and data lives in Cloud SQL, GCS, BigQuery or Pub/Sub.
- **GKE persistent volumes are an approved exception**, declared in `product.yaml` with a reason. They may hold only **data that is never shared and can be rebuilt** (cache, scratch, search index).
  - Disks are ReadWriteOnce Persistent Disks. Prod uses regional PD (2 zones). Non-prod uses zonal PD.
  - The **tenant chart** (Decision 15) creates **one StorageClass per customer per environment** (e.g. `sc-acme-prod`), which sets that customer's KMS key and the mandatory labels (Decision 9) on every disk.
  - Namespace ResourceQuota caps total storage and PVC count.
  - Prod uses `reclaimPolicy: Retain` and snapshots before decommission. Dev uses `Delete`.
  - Products with disks run as **StatefulSets** with at least 2 replicas and partitioned rolling updates. Argo Rollouts canary does not apply to them.
  - **Backup for GKE** (Google-managed) is used for cluster and volume backups, not Velero. Backup plans are per customer namespace (created by L3 Terraform), so a single customer can be restored. Prod backups are stored in the DR pair region.
- **Filestore is not used.** Shared files go to GCS, mounted read-only through the Cloud Storage FUSE CSI driver (GKE) or `gcsfuse` (MIG) where a product needs a file path.
- **Data that may need to be shared across environments must live in Cloud SQL, GCS or BigQuery.** PVCs are never shared, copied or seeded between environments. Disk snapshots are used only to restore within the same environment.

### 7. Data sharing within a customer (three explicit flows)
The scenario requires that a customer's data can be shared between that customer's own environments. This is delivered through three one-way, audited flows. There are **no live cross-environment database connections**, and no customer can ever reach another customer's data.

| Flow | Direction | Typical content | Mechanism |
|---|---|---|---|
| **Shared reference** | All 4 environments read | Master data, catalogs, feature flags | The customer's shared bucket and dataset in `data-exchange`, read-only for every environment identity of that customer. Written only by the promote pipeline. GKE and MIG workloads can mount the bucket read-only. |
| **Promote up** | dev → stage → uat → prod | Customer configuration, templates and content built in lower environments | Versioned export packages (config-as-code in Git, or a product-provided export/import API), promoted by a pipeline with an approval at each step. Lower environments never write into prod. |
| **Seed down** | prod → uat / stage / dev | Realistic test data | See the steps below. BigQuery uses a scheduled query that writes anonymized tables to the exchange. GCS uses Storage Transfer Service with sensitive prefixes excluded. Scheduled (default weekly) or on demand. Stays in the customer's region. |

**Seed-down steps for Cloud SQL** (one run covers all of the customer's products, because they are schemas in the same database):
1. Export the customer's prod database (`acme_prod`) with the native Cloud SQL export.
2. Import it into a **temporary scratch instance inside the prod perimeter**.
3. Run the sanitization SQL, then the verification checks, and write the `_clone_metadata` marker.
4. Map ownership for the target environment: create a `NOLOGIN` role named after the target login on the scratch instance, then `REASSIGN OWNED` from the prod login to it, so the import cannot fail on missing roles.
5. Export the sanitized database, publish the dump to `data-exchange`, and delete the scratch instance.
6. A **non-prod import job** (non-prod identity) reads the dump from the exchange, recreates the target database (e.g. `acme_corp_uat`), imports it as the target login, and reruns the database bootstrap job for that database. No prod identity ever writes into non-prod.

- Policy per customer, in `customers/<name>/data-sharing.yaml`:
  ```yaml
  sharedReference: true
  promoteUp: { enabled: true, approvals: [customer-success] }
  seedDown:  { targets: [uat, stage], mode: sanitized, schedule: weekly }   # or targets: []
  ```
  Terraform turns this policy into the IAM grants. The isolation tests check them.
- **Mandatory sanitization before anything leaves prod:**
  - Auth: replace password hashes with a known test hash, null salts, MFA secrets, backup codes, recovery keys and security questions
  - Truncate sessions and all token tables (refresh, access, OAuth, remember, password reset, email verification)
  - Replace API keys with `TEST_`-prefixed keys, regenerate webhook and OAuth client secrets, null third-party tokens
  - Null payment tokens and card fingerprints, replace payment-provider customer IDs with test IDs
  - Anonymize PII (email, phone, name, address, national ID)
- **Automated verification** (password hashes replaced, MFA disabled, token tables empty, API keys prefixed) writes a `_clone_metadata` marker. A target environment cannot use the data until verification passes. Failure alerts and stops the flow.
- **Excluded from all flows:** persistent volumes and Pub/Sub messages. Event data worth sharing must first be written to BigQuery or GCS.
- **Version-compatibility guard:** seed down and promote up require the source and target product versions to be inside the declared schema-compatibility window, checked per product schema.
- GCP-native operations only (Cloud SQL export/import, BigQuery scheduled queries, Storage Transfer Service). The Cloud Function only orchestrates them and runs the sanitization SQL. No custom ETL.

### 8. Encryption and identity
- **Per-customer KMS key ring** in `security-nonprod` (Dev/Stage and UAT groups) or `security-prod` (prod), per environment group, in the locations the customer's resources need: the customer's region, the DR pair region, and for dual-region prod buckets the matching multi-region (`us`, `europe`) or predefined dual-region code.
- GCS buckets, BigQuery datasets and persistent disks use the customer's key. Disabling it crypto-shreds that customer's data on offboarding.
- **Cloud SQL encryption keys apply per instance, not per database.** Pooled instances therefore use a platform key, and products apply **application-level envelope encryption with the customer's KMS key** to sensitive columns, so destroying that key crypto-shreds the customer's sensitive data. Customers that need their own instance key take `isolation: dedicated`.
- **GKE identity:** grant IAM directly to Kubernetes service accounts through Workload Identity Federation for GKE for GCS (uniform bucket-level access), BigQuery, Pub/Sub, KMS and Secret Manager. For Cloud SQL login (and GCS signed URLs), pods impersonate the customer's environment service account.
- **Customer environment service account:** one Google service account per customer per environment. It is the Cloud SQL login for every runtime and the identity of that customer's Cloud Run services and MIGs. It lives in the compute project of its environment group (`compute-devstage`, `compute-uat`, `compute-prod`). That is 200-1,000 accounts per project, above the default quota (commonly 100), so L1 requests quota increases. If an increase is refused, add an identity project per environment group under the quota trigger.
- **Database access:** `CONNECT` on a customer's database is granted only to that customer's environment login. Isolation between customers is enforced by `CONNECT`, which the database bootstrap job sets. Between one customer's products, schemas are separated by convention (each product's migrations own its schema), not enforced, because the products share one login.
- Resource-level IAM only, apart from the conditional exceptions in Decision 4. Tokens ≤ 1 hour. No shared credentials across customers or environments.
- **Isolation tests** are delivered as code. They run against a real environment on a schedule and in the release pipeline: for a sample of customer pairs, customer A's identities must fail to reach customer B's database, schema, dataset, bucket, topic, namespace and key. A failure blocks the release. The public repo CI runs the static policy checks instead (see "Public repository constraints").

### 9. Labels, naming and resource identification
- Customers are billed by their **product subscription price**, not by the GCP cost of their resources. Per-customer cost attribution is therefore **not required**, and there is no cost-allocation engine.
- Labels exist so that **any resource can be identified quickly**: whose it is, which product and environment it serves, and who manages it. They are used for operations, incident response, audits, inventory and offboarding.
- **Mandatory labels on every GCP resource that supports labels**, and the same keys as Kubernetes labels on every namespace and workload:

  | Label | Example | Purpose |
  |---|---|---|
  | `customer` | `acme-corp` (`shared` for platform resources) | Owner customer |
  | `environment` | `dev` / `stage` / `uat` / `prod` | Environment |
  | `env-group` | `devstage` / `uat` / `prod` | Environment group |
  | `product` | `payment-api` (`platform` for shared resources) | Product served |
  | `region-role` | `primary` / `dr` | Primary or DR copy |
  | `managed-by` | `terraform` / `argocd` | What owns the resource, to catch manual changes |

- Label values follow GCP rules (lowercase letters, digits, `_` and `-`, up to 63 characters). Every Terraform module, the product base chart and the tenant chart set them. A static label check in CI fails any module or chart that misses one.
- **Naming convention**, so a resource is recognizable even where labels are not supported:

  | Resource | Pattern | Example |
  |---|---|---|
  | Namespace | `{customer}-{env}` | `acme-prod` |
  | Cloud Run service, MIG | `{customer}-{product}-{env}` | `acme-reporting-prod` |
  | GCS bucket | `{prefix}-{customer}-{product}-{env}` | `pfx-acme-reporting-prod` |
  | BigQuery dataset | `{customer}_{product}_{env}` | `acme_reporting_prod` |
  | Cloud SQL database / schema | `{customer}_{env}` / `{product}` | `acme_prod` / `reporting` |
  | Pub/Sub topic | `{customer}-{product}-{env}-{name}` | `acme-payment-prod-events` |

  - GCS bucket names are **globally unique across all of GCP**, so every bucket starts with a platform prefix (`{prefix}`, e.g. an organization short code).
  - To stay within GCP name-length limits, customer IDs are capped at 20 characters and products use short codes of up to 12 characters (`payment-api` → `payment`).
- **Platform cost visibility only:** the billing export to BigQuery lets the platform team see spend per project, environment group, region and product, using the same labels. Budget alerts at 50/80/100% are set per project. No per-customer cost reporting, invoicing or FinOps dashboards.
- Namespace ResourceQuotas stay, for fair sharing and capacity protection rather than billing.

### 10. HA and DR
**Every prod customer gets HA and DR by default.**

| Component | HA (zone failure, automatic) | DR (region failure, warm standby in the pair region) |
|---|---|---|
| GKE | Regional cluster, 3 zones, PDBs | **Dedicated DR cluster** (`<prod-cluster>-dr`) at minimum size. The prod ArgoCD deploys every prod app to it at minimum replicas. It scales up on failover. |
| Cloud SQL | Regional HA (synchronous standby) | Enterprise Plus advanced DR: cross-region replica with switchover and failover. The write endpoint follows the primary. |
| Cloud Run | Multi-zone by default | Same service deployed in the pair region behind the global LB |
| MIG | Regional MIG, 3 zones, autohealing | Stateless MIG in the pair region at minimum size, scaled up on failover |
| GCS | Not applicable | Dual-region buckets across the pair, with turbo replication |
| BigQuery | Not applicable | Daily cross-region copy to the pair region. Not part of regional failover. |
| Pub/Sub | Global service | Storage restricted to the pair. Subscriptions re-pointed to the DR Cloud Run on failover. |
| Persistent volumes | Regional PD | Backup for GKE backups in the pair region, restored on failover |
| Edge | Global LB health checks | Global LB fails the customer's hostnames over to DR backends |
| Supporting | Not applicable | Secrets replicated to the pair. Prod Artifact Registry multi-region. KMS keys in both regions. |

| Profile | RTO | RPO |
|---|---|---|
| Zone failure (HA) | ~1-5 min | 0 |
| **Region failure, warm standby (default)** | **~30 min** | **~5 min** |
| Region failure, `dr: hot-standby` (opt-in, DR cluster at full size) | ~5 min | ~1 min |
| Non-prod (backup and restore, no DR) | 4 h | 24 h |

| Data | Region-failure RPO |
|---|---|
| Cloud SQL | ~5 min (~1 min with hot standby) |
| GCS | ≤15 min (turbo replication) |
| BigQuery | 24 h (daily cross-region copy) |

- **DR clusters are dedicated**, not the pair region's own prod clusters, so a failover never doubles the load on another cell.
- **Failover happens per cell, not per customer.** A Cloud SQL failover moves the whole pooled instance, so every customer on that cell fails over together. Each prod cell has its own Cloud SQL instance, so a failover moves exactly one cell.
- **Database endpoint:** workloads connect through the Cloud SQL write endpoint, which follows the primary after switchover or failover. It needs Enterprise Plus, private services access and the Cloud DNS API. Keep per-region connection configuration as a fallback until write-endpoint resolution across Shared VPC projects is tested.
- Runbooks cover failover (Cloud SQL DR failover, confirm the write endpoint, scale up DR, switch LB) and failback.
- Backups: Cloud SQL daily (30 days) plus point-in-time recovery (7 days), Backup for GKE daily (14 days), GCS versioning plus soft delete, quarterly failover tests per cell.
- Prod Cloud SQL pools run on Enterprise Plus. Replicas must be the same size as the primary to take the load. State the cost impact (roughly double the fixed prod footprint per region).
- These are design targets. Replica lag and promotion time must be proven in the DR tests.

### 11. Edge and internet exposure
- **Dev/Stage:** regional internal Application Load Balancers per region, reached only through VPN/IAP. No internet exposure.
- **UAT:** one global external Application LB with a Cloud Armor IP allowlist.
- **Prod:** one global external Application LB. It routes each customer's hostname to the backends in that customer's region, and to the DR region on failover.
- **GKE prod path:** Internet → Cloud Armor → Global HTTPS LB → Cloud CDN → Istio Ingress Gateway → pods
- **Cloud Run prod path:** Internet → Cloud Armor → Global HTTPS LB → serverless NEG → Cloud Run (ingress = internal-and-cloud-load-balancing)
- **MIG prod path:** Internet → Cloud Armor → Global HTTPS LB → backend service → regional MIG
- **Cloud Armor:** DDoS, OWASP WAF, geo-blocking, bot management, and **rate limiting per client IP and per customer** (keyed on the request host or a customer header).
- **API authentication without an API gateway:**
  - GKE: Istio `RequestAuthentication` validates JWTs at the ingress gateway, and `AuthorizationPolicy` enforces required claims (including the customer ID matching the host).
  - Cloud Run and MIG: the application validates JWTs using a shared platform library. IAP is used for internal and operator access.
- **API versioning** is path-based (`/v1/`, `/v2/`), routed by the LB URL map and Istio VirtualServices.
- **API management (Apigee) is out of scope for now.** If it is needed later (API monetization, developer portal, complex request transformation), it can be inserted between the LB and the backends without changing the backends.
- **DNS (Cloud DNS):** prod `{customer}.platform.example` and `api.{customer}.platform.example`. Non-prod `{customer}.{env}.platform.internal` in private zones. Custom domains via CNAME.
- **Certificates:**
  - Prod: Certificate Manager with DNS authorization, a wildcard certificate per customer (`*.{customer}.platform.example`, which covers `api.{customer}…`), served through certificate maps. Customer-provided certificates are added to the map when `edge.customCertificate` is set. Verify Certificate Manager limits for 200+ customers in Phase 1.
  - Non-prod: a private CA (Certificate Authority Service) for `*.{env}.platform.internal`.

### 12. Service mesh and traffic
- **GKE:** Istio on all workloads. PeerAuthentication STRICT. AuthorizationPolicy plus Sidecar scoping for namespace isolation. Default-deny egress (Istio + NetworkPolicy + VPC firewall), ServiceEntry allowlist, egress gateway, Cloud NAT static IPs. Observability: Cloud Trace, Prometheus + Cloud Monitoring, Envoy access logs.
- **Cloud Run and MIG** (no mesh): per-service identity and IAM invoker bindings instead of AuthorizationPolicy. Direct VPC egress (Cloud Run) or VPC firewall with per-tenant network tags (MIG), plus Cloud NAT. TLS from the LB to the backend instead of sidecar mTLS.

### 13. Zero-downtime deployment
- **GKE stateless:** rolling by default (maxSurge 25%, maxUnavailable 25%). Canary via Argo Rollouts + Istio (10→25→50→100% with AnalysisTemplate and automatic rollback). Blue-green for major releases or database migrations. PDB, readiness/liveness probes (`/healthz/ready`, `/healthz/live`), preStop sleep 15s.
- **GKE stateful (approved PVC products):** StatefulSet, partitioned rolling update, one pod at a time, at least 2 replicas.
- **Cloud Run:** new revision with no traffic, staged traffic split (10→25→50→100%), automatic rollback on a health/SLO check. Min instances in prod.
- **MIG (stateless):** rolling update with `maxUnavailable=0` and `maxSurge` ≥ one zone's worth, autohealing, connection draining. Blue-green via a second MIG behind the same backend service for major changes.
- **Schema migrations** run before the new version takes traffic: an Argo CD sync hook Job (GKE), a Cloud Run job (Cloud Run), or an Ansible task (MIG). They follow expand/contract, so old and new versions work during the rollout.

### 14. Zero trust
- Identity: Decision 8.
- Network: mTLS on GKE, default-deny, VPC Service Controls (Decision 4), private clusters, Private Google Access, allowlisted egress.
- Workload: Binary Authorization for GKE and Cloud Run (with a documented break-glass procedure). Images built on GitHub and on Bitbucket are signed with the non-prod build key, and reach prod only through image promotion (Decision 17), which adds a prod attestation with the prod key. MIGs use Shielded VM and signed Packer images from a trusted image project. Artifact Registry scanning blocks CRITICAL/HIGH. Shielded GKE Nodes. Pod Security Standards "restricted".
- Data: per-customer keys (Decision 8), TLS 1.2+, DLP scanning, application-level encryption for PII.
- Monitoring: Security Command Center, Cloud Audit Logs to BigQuery/SIEM, Falco on GKE, alerting, automated remediation, regular pen tests.

### 15. GitOps and ArgoCD topology
- **One ArgoCD instance per environment group: Dev/Stage, UAT, Prod (3 in total).** The Dev/Stage and UAT instances run on the management cluster in `platform-nonprod`. The Prod instance runs on the management cluster in `platform-prod`. Each instance holds access only to its own group's clusters, so non-prod tooling can never touch prod.
- Clusters are private. Each management cluster sits in its environment's Shared VPC, so ArgoCD reaches clusters through their private endpoints (control-plane global access, authorized networks limited to the management cluster), authenticating with Workload Identity (`argocd-k8s-auth gcp`). No stored cluster credentials. L2 registers each new cluster with the right instance automatically. Connect Gateway is used only for operator access.
- **Tenant ApplicationSet:** generates one tenant Application per customer per environment from `customer.yaml` and its placement. It deploys the **tenant chart**: namespace, ResourceQuota, LimitRange, StorageClass, default-deny NetworkPolicies, Istio Sidecar and PeerAuthentication, and the Kubernetes service accounts. It also generates the customer's AppProject in the ArgoCD namespace.
- **Product ApplicationSets** generate one Application per customer × product × environment from `customers/*/products.yaml` and the placement. The prod ApplicationSet targets both the primary and the DR cluster (DR at minimum replicas).
- Scale settings: controller sharding, multiple repo-server replicas, Redis HA (ArgoCD's internal cache), GitHub webhooks instead of polling, and the `argocd.argoproj.io/manifest-generate-paths` annotation so a commit refreshes only the Applications it touches.
- **One AppProject per customer**, limited to that customer's namespaces and clusters.
- **Prod ApplicationSets create and update only, never delete.** An empty or broken generator must not remove Applications. Deletions go through the phased decommission.
- In-cluster platform software (Istio, Argo Rollouts, Backup for GKE agents, Falco, policies) is installed by ArgoCD from Git (app-of-apps). Terraform installs only ArgoCD itself.
- Rollout waves across customers are driven by version-pin PRs in batches.
- ArgoCD's desired state lives in Git, so an instance can be rebuilt. Document rebuilding the prod instance in a second region.
- **Escape hatch:** if one instance grows too large, split it by region. The ApplicationSets already filter by placement, so this is a configuration change.

### 16. Multi-product provisioning
- `products/<product>/product.yaml` (catalog, platform-owned) declares runtime, data services (Cloud SQL, GCS, BigQuery, Pub/Sub), optional persistent volume, sizing per environment, dependencies, networking and compliance.
- `customers/<customer>/products.yaml` declares enabled products, version per product per environment, overrides and product config.
- **Composition rules:**
  - Each enabled product gets, per environment: a schema in the customer's database, its own bucket, its own dataset and its own Pub/Sub topics, only if its catalog entry requires them.
  - Pub/Sub subscriptions are valid only for Cloud Run products. Publishers may be GKE or Cloud Run products.
  - Persistent volumes are valid only for GKE products whose catalog entry is approved.
  - Merge rule: the largest size wins, resources are unioned, customer overrides are applied last.
- Day 2 add / remove (phased decommission with data retention, approvals from platform-admin and customer-success) / upgrade, with PR validation, dependency checks, and the Terraform plan summary commented on every product-change PR.
- Removing a product drops its schema, bucket, dataset and topics after the retention period, without touching the customer's other products.

### 17. Shared infrastructure: CI and Ansible runners
The scenario lists GitHub/Bitbucket and Ansible runners as shared infrastructure.

| Pool | Runs | Where | Notes |
|---|---|---|---|
| **GitHub Actions runners** | Terraform plan/apply, placement, image builds for GitHub-hosted products (non-prod pool), image promotion (prod pool) | `platform-nonprod` and `platform-prod` | Actions Runner Controller on the management cluster (or ephemeral MIG). One job per runner. |
| **Bitbucket Pipelines runners** | Build, scan and sign for Bitbucket-hosted products | `platform-nonprod` | Same reusable build steps as GitHub: build, scan, sign with the non-prod build key, push to the non-prod Artifact Registry |
| **Ansible runners** | MIG configuration and migrations | `platform-nonprod` and `platform-prod` | Small MIG, OS Login, IAP-only SSH, no public IP. `google.cloud.gcp_compute` dynamic inventory filtered by labels. Reaches MIGs over private IP inside its own environment's VPC only. |

- **Separate pools for non-prod and prod.** The prod pool's identity can act only on prod projects, and the non-prod pool's only on non-prod projects. L1 (shared foundation) runs on the prod pool with an extra approval.
- **Image promotion:** builds (GitHub or Bitbucket) push only to the non-prod Artifact Registry, and non-prod clusters and services pull from there. Once an image is scanned and signed, a promotion job on the prod GitHub pool copies it **by digest** into the prod Artifact Registry. Prod clusters, Cloud Run services and MIG templates pull only from the prod registry. The promotion job verifies the non-prod attestation and adds a prod attestation signed with the prod key in `security-prod`. Prod Binary Authorization requires that attestation, so no key crosses a perimeter. Packer golden images follow the same pattern: built on the non-prod pool, then copied into the prod image family by the promotion job. The only cross-perimeter access is the prod promotion identity reading from non-prod.
- All runners are ephemeral, have no public IP, and reach GitHub/Bitbucket through Cloud NAT. They authenticate to GCP with workload identity federation (GitHub OIDC, Bitbucket OIDC). No service-account keys.
- Runners sit inside their environment's VPC-SC perimeter, which is why Terraform must run on them rather than on hosted runners.
- Fork PRs on the public repo never reach these runners (see "Public repository constraints").

## Version divergence and customization mechanism

1. **One codebase per product, immutable versioned artifacts.** Image tags and MIG image versions are pinned per customer per environment in `products.yaml`.
2. **Customization layers (in order of preference):** configuration values, feature flags, product-defined extension points. Customers with `variantImages: true` may get a **variant image** (e.g. `payment-api:2.5.0-acme.1`) built from a `customer-variants/` overlay in the product repo. Forks are not allowed.
3. **Support window:** latest N and N-2 minor versions. The validator rejects pins outside the window.
4. **Schema compatibility:** each product schema is migrated independently per customer, following expand/contract. The validator checks this on every version PR. Breaking migrations use blue-green and are sequenced per customer.
5. **Version matrix:** generated from `customers/*/products.yaml` in CI (customer × product × environment × version) and published as a build artifact and docs page.
6. **Environment skew:** dev may run a newer or beta version than prod. The version-compatibility guard in Decision 7 governs the data flows between them.

## Execution model (layers)

The platform is applied in layers. Each layer has its own Terraform state and runs after the one above it. The repo is organized this way, and the README states the apply order.

| Layer | What it creates | Tool | Triggered by | Runs on | State |
|---|---|---|---|---|---|
| **L0 Bootstrap** (manual, once) | Terraform service accounts, state bucket, GitHub and Bitbucket → GCP identity federation (no key files), top-level folders | Documented script | Platform team | Laptop | Local, then migrated to GCS |
| **L1 Foundation** (once) | Project factory creates the fixed projects. APIs, Shared VPCs, VPC-SC perimeters (dry-run until the self-hosted runners are live), org policies (including allowed regions), Artifact Registries (non-prod build target and prod promoted images), `security-nonprod` and `security-prod` baselines, `platform-*` projects with runner pools, management clusters and the 3 ArgoCD instances | Terraform | Platform PR + approval | GitHub-hosted for the first apply, then the prod pool | 1 state |
| **L2 Region** (per approved region, prod with its DR pair) | Subnets, routers, NAT, the 3 group clusters (+ dedicated prod DR cluster), Cloud SQL instances (+ cross-region replicas), regional exchange resources, KMS key locations, LBs and backends. **Writes `inventory/clusters/*.yaml` and `inventory/sql/*.yaml`**. Capacity (new cell) PRs also apply here. | Terraform, then ArgoCD installs in-cluster software | Approved platform PR | Pool of the environment group | 1 state per region per environment group |
| **L3 Customer** (per customer) | Cloud SQL databases and IAM database users, buckets, datasets, topics, KMS keys, identities and IAM, Cloud Run and MIG definitions, Backup for GKE plans, data-sharing grants. For `isolation: dedicated`, a project via the project factory (separate state, extra approver). **No Kubernetes objects** (those come from the tenant chart). The pipeline then runs the database bootstrap job. | Terraform (Google APIs only) | Customer PR (after placement) | Pool of the environment group | 1 state per customer per environment |
| **L4 Delivery** (every release) | Tenant chart, workloads, schema migrations and version rollouts | ArgoCD (GKE), Cloud Run deploy step, Packer + Ansible (MIG) | Change in `customer.yaml` or `products.yaml` | ArgoCD / runners | None (Git is the desired state) |

Rules:
- L3 reads cluster names, database instance names and the DR pair from `inventory/`, never hard-coded.
- Terraform uses only Google APIs. It never connects to a cluster or a database. Database grants and schemas are applied by the database bootstrap job. Self-hosted runners are still required because the projects sit inside VPC-SC perimeters, and Ansible needs private access to MIGs.
- **Changed-path detection:** a customer PR plans only that customer's states, never all 200+.
- **Drift detection:** a scheduled `terraform plan` per state, run in batches, alerting on any diff.
- **Project factory guardrails:** the factory service account holds Project Creator only on specific folders, has its own state, needs an extra approver on any PR that adds a project, and is constrained by an org policy on where projects may be created.

## Constraints

- GCP only. Terraform open-source CLI, version 1.7 or later (for `terraform test` mock providers). No Terraform Cloud/Enterprise/Spacelift/env0. Terragrunt only if you justify it against plain directories.
- Helm 3, ArgoCD ApplicationSets, Argo Rollouts, managed Istio, GitHub Actions, Bitbucket Pipelines (product repos only), Ansible for MIGs, Packer for golden images.
- Budget: optimize for cost, pool infrastructure with strong isolation, provision only what product selection needs, add regions only by approval.
- SOC 2 Type II, strict tenant isolation, least-privilege IAM, audit logging, VPC-SC, zero trust.
- Timeline: MVP in 4 weeks, production-ready in 12 weeks. Team: 5 engineers, automation-first.
- Data movement between environments: GCP-native services only. No custom ETL or sync scripts.

## Public repository constraints

- **Public GitHub repository named `platform-config`**, under the GitHub account or organization the user provides. Do not create or push it without the user's go-ahead. Share its URL in the final checklist.
- **No secrets and no real identifiers.** Use fake org/billing/project IDs (e.g. `000000000000`), `platform.example` domains, a placeholder bucket prefix, and placeholder customers (`acme-corp`, `beta-industries`). Include `.gitignore` for state and tfvars, and a secret-scan step in CI.
- **CI must be safe for a public repo.** PRs from forks run only offline checks, with **no secrets and no self-hosted runners**. Apply runs only from a protected branch with required reviewers via GitHub Environments. Self-hosted runners are documented as the production configuration and are never reachable from fork PRs.
- **Offline checks (the repo gate):**
  - Terraform: `fmt -check`, `validate`, `terraform test` with `mock_provider`, and static analysis (e.g. tflint, plus checkov or OPA/conftest) for mandatory labels, no project-level IAM for customer identities (except the allowlisted conditional grants in Decision 4), and no public IPs
  - Helm: `lint`, `template` for both example customers, schema validation of the rendered manifests (e.g. kubeconform), and policy checks for labels and Pod Security Standards
  - Placement script: unit tests against sample `inventory/` and `customers/` files
  - Secret scan
- Terraform uses a remote GCS backend **template** (documented, not configured with real values).
- Include README (purpose, structure, quickstart, apply order L0 → L4), CONTRIBUTING, LICENSE, and a "what is mocked" note.

## Assumptions
- GCP organization and billing exist. GitHub is available. Bitbucket is available for the product repos that use it. Customers are onboarded through PRs to the config repo.
- All GKE and Cloud Run products are containers in Artifact Registry. MIG products use Packer golden images.
- Product teams own application code, Helm values and schema migrations. The platform team owns base infrastructure, shared modules, the tenant chart and the catalog.
- Applications implement tenant context, expose `/healthz/ready` and `/healthz/live`, follow 12-factor, and keep shareable state in Cloud SQL, GCS or BigQuery.
- Products support configuration export/import (for promote up) and contain standard auth tables (users, sessions, tokens) for sanitization.
- DNS is Cloud DNS. No hybrid or on-prem connectivity.

## Non-goals
- Multi-cloud or hybrid. Customer self-service portal. Migration of existing workloads. On-prem connectivity.
- Customer invoicing and FinOps dashboards. Customer-managed catalog. Automatic product recommendations.
- Live cross-environment database access. Shared network filesystems (Filestore).
- API management platform (Apigee). Edge security is Cloud Armor plus the LB, with JWT validation at Istio or in the application.
- Design of streaming data pipelines (Pub/Sub is provided as a resource; product event design is out of scope).

## Success criteria

**Repo acceptance criteria** (checked by the reviewer and by CI on the public repo):
- D1 to D5 are present, and the scenario traceability table maps every scenario item and deliverable to the design.
- The three runtime diagrams exist as Mermaid and SVG.
- The repo gate passes in CI (see "Public repository constraints").
- The two example customers render end to end: placement output, Terraform for L3, the tenant chart and product Helm releases, and ApplicationSet output.
- No secrets or real identifiers in the repo.

**Platform targets** (design targets, proven during the real rollout):
- A new customer with 4 environments is provisioned in < 30 min from a PR that sets only `region.primary`. Placement (clusters and databases in the same region) is automatic and written back to Git.
- A new product on an existing customer is live in < 20 min. A version update needs zero manual steps.
- Zero-downtime deployments with automatic rollback on all three runtimes.
- No cross-customer data or network access is possible, proven by the isolation tests against a real environment.
- Data-sharing flows work inside the customer boundary. Seed down completes in < 30 min with verified sanitization. No prod credentials ever exist in non-prod.
- Every prod customer has HA and DR. Prod availability 99.9%. Warm-standby RTO ~30 min / RPO ~5 min (hot standby ~5 min / ~1 min). Quarterly failover tests pass per cell.
- The project count stays at about 12 regardless of customer count (plus opt-in dedicated projects). Adding a region needs one approved platform PR.
- Every resource carries the mandatory labels (Decision 9), so any resource can be traced to its customer, product and environment, and all of a customer's resources can be listed by label.
- All changes are auditable, peer-reviewed and version-controlled. Cluster upgrades pass Dev/Stage and UAT before prod.
- Supports 500+ customers without redesign. Platform cost grows slower than customer count, through pooling.
- Zero critical/high vulnerabilities in prod images. Controls pass SOC 2 Type II.

## Stakeholders
Platform Engineering (Terraform, CI/CD, runners, ArgoCD, Istio, tenant and base charts, data flows, catalog infrastructure, region approvals). Product Teams (application code, Helm values, schema migrations, health checks, config export/import, infrastructure requirements). Customer Success/Operations (onboarding PRs, options, add/remove requests, promote-up approvals). Security & Compliance. SRE (HA/DR, failover tests, capacity). Finance (platform spend per project and product).

## Risks to address explicitly
Terraform state at scale (200+ customers × 4 environments). Helm values sprawl. Cost explosion, including the DR footprint. Shared-cell blast radius and per-cell failover. RBAC complexity. A tenant-context bug leaking data. Drift. Onboarding bottleneck. Version matrix and per-customer schema migrations. Istio overhead. Canary metric quality. Cross-region replica lag and database endpoint switch on failover. Binary Authorization friction. Sanitization failure. Role mapping during seed-down imports. A database left with default `PUBLIC` access if the bootstrap job does not run. Promote-up depending on product export/import support. Object counts and quotas (about 4,000 buckets and 4,000 datasets at 200 customers × ~5 products × 4 environments, service accounts, Cloud Run services per region per project, Certificate Manager certificates). Global uniqueness of bucket names. IP address planning across regions. ArgoCD scale per instance. VPC-SC rules for services shared across perimeters. Catalog drift. Accidental product-removal data loss. Public-repo exposure (fork PRs, leaked identifiers). Cloud Run/MIG isolation (weaker native boundary than namespaces).

## Reference patterns

1. **Resource hierarchy**
```
Organization
└── Folder: Platform
    ├── Folder: Network        → net-nonprod, net-prod
    ├── Folder: Compute        → compute-devstage, compute-uat, compute-prod
    ├── Folder: Data           → data-nonprod, data-prod, data-exchange
    ├── Folder: Platform       → platform-nonprod, platform-prod
    ├── Folder: Security       → security-nonprod, security-prod
    └── Folder: Dedicated-Customers (only `isolation: dedicated`)
        └── Folder: {customer} → Project: {customer}-dedicated   (project factory)
```
Regions and cells are resources inside these projects, not projects.

2. **Region inventory** (`inventory/regions.yaml`, platform-managed)
```yaml
regions:
  - name: us-east1
    status: active
    drPair: us-central1
    cidr: { nonprod: 10.10.0.0/16, prod: 10.110.0.0/16 }
  - name: us-central1
    status: active
    drPair: us-east1
    cidr: { nonprod: 10.11.0.0/16, prod: 10.111.0.0/16 }
  - name: europe-west1
    status: reserved            # IP ranges reserved, nothing created yet
    drPair: europe-west4
    cidr: { nonprod: 10.20.0.0/16, prod: 10.120.0.0/16 }
```

3. **Cell inventory** (written by L2, never hand-edited)
```yaml
# inventory/clusters/prod-us-east1-01.yaml
name: prod-us-east1-01
group: prod
region: us-east1
project: compute-prod
status: active                  # active | full | draining
capacity: { maxCustomers: 25 }
drCluster: { name: prod-us-east1-01-dr, region: us-central1 }   # dedicated DR cluster
sqlInstances: [sql-prod-us-east1-01]
```
```yaml
# inventory/sql/sql-prod-us-east1-01.yaml
name: sql-prod-us-east1-01
group: prod
region: us-east1
project: data-prod
status: active
capacity: { maxCustomers: 25 }   # one instance per prod cell
replica: { region: us-central1, name: sql-prod-us-east1-01-dr }
```

4. **Customer config** (`customers/acme-corp/customer.yaml`)
```yaml
apiVersion: platform.example/v1
kind: CustomerConfig
metadata:
  name: acme-corp                      # customer ID, max 20 characters
spec:
  displayName: "Acme Corporation"
  accountId: "CUST-000001"
  region:
    primary: us-east1                  # the only onboarding input
  options:                             # all default off
    isolation: shared                  # shared | dedicated
    dr: warm-standby                   # warm-standby (default) | hot-standby
    edge: { customCertificate: false, customDomain: null }
    variantImages: false
  placement:                           # written back by the placement job, never hand-edited
    devstage: { cluster: devstage-us-east1-02, sqlInstance: sql-nonprod-us-east1-01 }
    uat:      { cluster: uat-us-east1-01,      sqlInstance: sql-nonprod-us-east1-01 }
    prod:     { cluster: prod-us-east1-01,     sqlInstance: sql-prod-us-east1-01,
                drCluster: prod-us-east1-01-dr }
  contacts:
    technical: devops@acme.example
```

5. **Product catalog excerpt** (`products/reporting-engine/product.yaml`)
```yaml
apiVersion: platform.example/v1
kind: ProductDefinition
metadata:
  name: reporting-engine
spec:
  shortCode: reporting                             # max 12 characters, used in names
  runtime: { type: cloud-run }
  data:
    cloudSql: { required: true }                   # becomes schema "reporting" in the customer's database
    storage:  { required: true }
    bigQuery: { required: true }
    pubsub:   { subscribe: [payment-events] }      # subscribe allowed for cloud-run only
  persistentVolume: { required: false }            # GKE only, needs approval
  dependencies: { required: [payment-api] }
```

6. **What one customer gets**
- 4 namespaces across 3 clusters (plus the DR cluster for prod), created by the tenant chart, or the matching Cloud Run services and MIGs
- 4 Cloud SQL databases (one per environment, aligned with the cluster region), each with one schema per enabled product, reached through the customer's environment login
- Per enabled product, per environment: a bucket, a dataset and Pub/Sub topics as the catalog requires
- One shared bucket and one shared dataset in the exchange
- A KMS key ring per environment group in the required locations
- Identities per environment, an AppProject, Backup for GKE plans, data-sharing grants
- 3 files in Git: `customer.yaml`, `products.yaml`, `data-sharing.yaml`

Onboarding creates exactly this. Offboarding deletes exactly this.

7. **Repository layout (public repo)**
```
platform-config/
├── README.md  CONTRIBUTING.md  LICENSE  .gitignore
├── docs/
│   ├── architecture.md                  # D1, including the scenario traceability table
│   ├── decisions.md
│   └── diagrams/
│       ├── gke.md  cloud-run.md  instance-group.md  (+ .svg)    # D2 (required)
│       └── hierarchy.md  regions.md  data.md  data-sharing.md  network-security.md  ha-dr.md  multi-product.md  runners.md
├── inventory/                           # regions.yaml + clusters/ + sql/ (clusters and sql written by L2)
├── products/_schema/  products/<product>/product.yaml
├── customers/_schema/  customers/{acme-corp,beta-industries}/{customer,products,data-sharing}.yaml
├── scripts/placement/                   # placement script + unit tests
├── tests/isolation/                     # isolation tests (run against a real environment)
├── policy/                              # OPA/conftest or checkov rules (labels, IAM, public IPs, PSS)
├── infrastructure/                      # D3
│   ├── modules/{project-factory,network,runner-pools,gke-cluster,cloud-run-service,mig-service,cloud-sql-instance,cloud-sql-database,storage,bigquery,pubsub,kms,backup-plan,data-sharing,load-balancer,customer-infrastructure,platform}/
│   └── layers/
│       ├── L0-bootstrap/
│       ├── L1-foundation/
│       ├── L2-region/{us-east1,us-central1}/{devstage,uat,prod}/
│       └── L3-customer/{acme-corp,beta-industries}/{dev,stage,uat,prod}/
├── helm/                                # D4
│   ├── tenant/                          # namespace, quota, LimitRange, StorageClass, NetworkPolicies, Istio Sidecar/PeerAuthentication, KSAs
│   ├── product-base/                    # Rollout, StatefulSet option, Service, PDB, migration hook Job, Istio VS/DR/AuthZ/ServiceEntry, HPA
│   └── values/{products,environments,customers}/
├── argocd/                              # 3 instances: app-of-apps, tenant and product ApplicationSets per group
├── ansible/  packer/                    # Instance Group path
├── db-bootstrap/                        # database bootstrap job: revoke PUBLIC, grant CONNECT, product schemas
├── data-flows/                          # seed-down function, sanitize.sql, verify, role mapping, promote-up pipeline
├── ci-templates/                        # reusable build/scan/sign steps for GitHub Actions and Bitbucket Pipelines, and image promotion by digest
└── .github/workflows/                   # fmt/validate, terraform-test (mocked), policy-check, helm-render, placement-tests, version-matrix, secret-scan
```

## Output format and phases

Work in phases. Complete and validate each before moving on. Do not produce everything in one response.

**Resuming work:** if the repository already contains `docs/STATUS.md`, read it first. It records which phases are complete and approved. Resume from the next phase, treat `docs/` as the approved design baseline, and do not redo completed phases or the Phase 1 verification.

**Depth of implementation** (the 4-week MVP cannot implement everything fully):
- **Implement fully:** L0 script, L1 (project factory, network, VPC-SC, runner pools, management clusters), L2 (clusters, Cloud SQL instances and replicas, LBs, exchange), the L3 composition module and its data/identity modules, Cloud Run and MIG service modules, the placement script with tests, the database bootstrap job, the tenant chart, the product base chart, the ApplicationSets, and the two example customers.
- **Skeleton plus documentation:** the seed-down function and sanitization SQL (structure, templates, verification), the promote-up pipeline, the isolation tests, the Packer/Ansible path (one minimal working example), the DR runbooks, and the Falco/SCC configuration.
- State the depth of each component in the README.

**Phase 1: Design and the three required diagrams**
1. Resource hierarchy diagram (Mermaid): the fixed projects, folders, VPC-SC perimeters, and where regions and cells sit inside the projects
2. **GKE architecture diagram**: the 3 environment groups, namespaces from the tenant chart, Istio, ingress/egress per group, ArgoCD path, dedicated prod DR cluster
3. **Cloud Run architecture diagram**: services per customer-product-environment, serverless NEG, Pub/Sub push/Eventarc delivery, IAM, revisions and traffic split, DR copy
4. **Instance Group architecture diagram**: stateless regional MIGs, Packer image pipeline, Ansible runners, LB, firewall tags, DR copy
5. Supporting diagrams: region model and placement, data architecture, data-sharing flows (shared reference, promote up, seed down), multi-product composition, network and security, HA/DR, runner topology
6. Key decisions table (`Decision Area | Options Considered | Recommendation | Rationale`), covering at least: environment groups, project model, database per customer with schema per product, data-sharing flows, per-instance Cloud SQL keys, ArgoCD topology, tenant chart vs Terraform for Kubernetes objects, warm-standby DR, API authentication without a gateway, runner pools, version divergence, and Cloud Run/MIG isolation
7. Scenario traceability table (each scenario item and deliverable → design section)

**Phase 1 verification task:** before finalizing Phase 1, check these GCP limits and features against current Google documentation. Report each result, and adjust the design where a limit does not fit:
- Service-account quota per project, and bucket and dataset counts at this scale (about 4,000 each)
- Cloud Run services per region per project
- BigQuery cross-region dataset replication for each region pair
- KMS key location required for dual-region GCS buckets and BigQuery replicas
- Workload Identity Federation for GKE support for each target service (Cloud SQL, GCS, BigQuery, Pub/Sub, KMS, Secret Manager)
- ArgoCD access to private clusters through private endpoints with control-plane global access
- Certificate Manager limits (certificates and certificate map entries) for 200+ customers
- Cloud SQL cross-region replica promotion and whether a DR write endpoint is available for the chosen edition
- Cloud SQL import behaviour for role ownership (for the seed-down role mapping)
- VPC-SC rules for the promotion job reading the non-prod Artifact Registry, and CMEK keys kept inside each perimeter

**Phase 2: Terraform (D3)**
8. Modules and layers L0-L3 as in the repo layout. Include the project factory, runner pools, the region layer (with DR pair, dedicated DR clusters and inventory output), the customer composition module (reads `product.yaml`, `products.yaml`, `data-sharing.yaml` and the placement), per-runtime modules, backup plans, and mandatory labels. Two example customers: one GKE + Cloud Run with Pub/Sub, one with a MIG product. Provide the placement script with unit tests, and the database bootstrap job (Cloud Run job) with its SQL. Validate with `terraform fmt -check`, `terraform validate`, `terraform test` (mock providers) and the static policy checks.

**Phase 3: Helm and ArgoCD (D4)**
9. The tenant chart and the product base chart with values hierarchy (base → product → environment → customer), Argo Rollout, StatefulSet option, migration hook Job, PDB, Kubernetes service accounts for Workload Identity Federation, Istio resources, per-customer version pins. The 3 ArgoCD app-of-apps setups, the tenant ApplicationSet and the product-aware ApplicationSets (prod targets primary and DR, create/update only). Validate with `helm lint`, `helm template`, schema validation and policy checks for both example customers.

**Phase 4: Supporting artifacts and repo packaging (D5)**
10. Product catalog: full schema, 3-4 example products across all three runtimes, requirement matrix, dependency graph
11. Data-sharing flows: seed-down Cloud Function structure, sanitization SQL template, verification, role mapping, BigQuery anonymization query, promote-up pipeline
12. CI/CD: build/scan/sign templates for GitHub Actions and Bitbucket Pipelines, image promotion by digest, Binary Authorization and break-glass, ArgoCD sync, canary per runtime, placement, product-change validation, label and policy checks, version matrix, isolation tests, public-repo-safe workflows
13. Day 2 workflows (add, remove, upgrade, drift), customer onboarding (step-by-step with time estimates), region addition, cell capacity addition, and DR failover/failback runbooks
14. 12-week roadmap (weeks 1-4 MVP, 5-8 hardening and data flows, 9-12 rollout and DR tests) with a product catalog timeline
15. README, CONTRIBUTING, push to the public GitHub repo, a final checklist against D1-D5 and the repo acceptance criteria, and the repository URL

After each phase, list what was produced, what is mocked, and any assumptions you had to make. Ask before changing any locked decision.

