# L3 composition: one customer, one environment (architecture §6, §8, §10, §17).
# Reads customer.yaml (with placement), products.yaml, the catalog and the inventory from Git and
# creates the customer's identity, database + login, per-product buckets, datasets, topics,
# Cloud Run services and MIGs (plus prod DR copies), and the Backup for GKE plan.
# Google APIs only: no Kubernetes objects (tenant chart) and no database connections (bootstrap job).

module "registry" {
  source    = "../registry"
  repo_root = var.repo_root
}

locals {
  reg  = module.registry
  c    = var.customer
  env  = var.environment
  cust = local.reg.customers[local.c].spec

  group       = local.reg.envs[local.env].group
  side        = local.reg.envs[local.env].side
  gcfg        = local.reg.platform.groups[local.group]
  is_prod     = local.env == "prod"
  hot_standby = try(local.cust.options.dr, "warm-standby") == "hot-standby"
  isolation   = try(local.cust.options.isolation, "shared")

  region     = local.cust.region.primary
  pair       = local.reg.regions[local.region].drPair
  multi      = local.reg.regions[local.region].multiRegion
  zones      = local.reg.regions[local.region].zones
  pair_zones = local.reg.regions[local.pair].zones
  placement  = try(local.cust.placement[local.group], null)
  prefix     = local.reg.platform.bucketPrefix

  compute_project  = local.reg.projects[local.gcfg.computeProject]
  compute_number   = local.reg.project_numbers[local.gcfg.computeProject]
  data_project     = local.reg.projects[local.gcfg.dataProject]
  data_number      = local.reg.project_numbers[local.gcfg.dataProject]
  security_project = local.reg.projects[local.gcfg.securityProject]
  platform_project = local.reg.projects[local.gcfg.platformProject]
  host_project     = local.reg.projects["net-${local.side}"]
  network          = "projects/${local.host_project}/global/networks/vpc-${local.side}"

  c_            = replace(local.c, "-", "_")
  database      = "${local.c_}_${local.env}"
  namespace     = "${local.c}-${local.env}"
  gsa_email     = "${local.c}-${local.env}@${local.compute_project}.iam.gserviceaccount.com"
  gsa_member    = "serviceAccount:${local.gsa_email}"
  workload_pool = "${local.compute_project}.svc.id.goog"
  ksa_principal = "principal://iam.googleapis.com/projects/${local.compute_number}/locations/global/workloadIdentityPools/${local.workload_pool}/subject/ns/${local.namespace}/sa"
  tenant_tag    = "t-${local.c}-${local.env}"

  # Customer keys are created by the keys-<side> state (decisions #24) and referenced by ID.
  key_fmt = "projects/${local.security_project}/locations/%s/keyRings/kr-${local.c}-${local.group}/cryptoKeys/${local.env}-%s"
  data_key = {
    region = format(local.key_fmt, local.region, "data")
    pair   = format(local.key_fmt, local.pair, "data")
    multi  = format(local.key_fmt, local.multi, "data")
  }
  app_key = format(local.key_fmt, local.region, "app")

  # ------------------------------------------------------------------ products enabled for this customer
  products = {
    for name, cfg in local.reg.customer_products[local.c] : name => {
      name         = name
      short        = local.reg.products[name].spec.shortCode
      short_       = replace(local.reg.products[name].spec.shortCode, "-", "_")
      runtime      = local.reg.products[name].spec.runtime
      data         = local.reg.products[name].spec.data
      dependencies = try(local.reg.products[name].spec.dependencies.required, [])
      pv           = try(local.reg.products[name].spec.persistentVolume.required, false)
      egress       = length(try(local.reg.products[name].spec.egress.allow, [])) > 0
      sizing       = merge(try(local.reg.products[name].spec.sizing[local.env], {}), try(cfg.overrides[local.env], {}))
      version      = try(cfg.versions[local.env], null)
      decommission = try(cfg.decommission, false)
    }
  }
  gke = { for k, p in local.products : k => p if p.runtime.type == "gke" }
  run = { for k, p in local.products : k => p if p.runtime.type == "cloud-run" }
  mig = { for k, p in local.products : k => p if p.runtime.type == "mig" }

  # The identity a product uses for its own data containers: KSA principal (GKE) or env GSA.
  member   = { for k, p in local.products : k => p.runtime.type == "gke" ? "${local.ksa_principal}/${p.short}" : local.gsa_member }
  deletion = { for k, p in local.products : k => local.is_prod && !p.decommission ? "PREVENT" : "DELETE" }

  buckets  = { for k, p in local.products : k => "${local.prefix}-${local.c}-${p.short}-${local.env}" if try(p.data.storage.required, false) }
  datasets = { for k, p in local.products : k => "${local.c_}_${p.short_}_${local.env}" if try(p.data.bigQuery.required, false) }
  schemas  = sort([for k, p in local.products : p.short if try(p.data.cloudSql.required, false)])

  topics = merge({}, [for k, p in local.products : {
    for t in try(p.data.pubsub.publish, []) : "${p.short}-${t}" => {
      product = k
      name    = "${local.c}-${p.short}-${local.env}-${t}"
    }
  }]...)
  subscriptions = merge({}, [for k, p in local.products : {
    for s in try(p.data.pubsub.subscribe, []) : "${local.c}-${p.short}-${local.env}-from-${s}" => {
      subscriber = k
      topic      = s
    }
  }]...)
  subscribers = toset([for s in values(local.subscriptions) : s.subscriber])

  # ------------------------------------------------------------------ labels
  label_sets = merge(
    { "platform/primary" = { product = "platform", role = "primary" } },
    { for k, p in local.products : "${p.short}/primary" => { product = p.short, role = "primary" } },
    local.is_prod ? { for k, p in local.products : "${p.short}/dr" => { product = p.short, role = "dr" } } : {},
  )
  labels = { for k, l in module.labels : k => l.labels }

  common_env = {
    CUSTOMER    = local.c
    ENVIRONMENT = local.env
    REGION      = local.region
    DB_INSTANCE = try("${local.data_project}:${local.region}:${local.placement.sqlInstance}", "")
    DB_NAME     = local.database
    DB_USER     = trimsuffix(local.gsa_email, ".gserviceaccount.com")
    KMS_APP_KEY = local.app_key
  }
}

module "labels" {
  source   = "../labels"
  for_each = local.label_sets

  customer    = local.c
  environment = local.env
  env_group   = local.group
  product     = each.value.product
  region_role = each.value.role
}

# ------------------------------------------------------------------ guards (fail the plan early)

resource "terraform_data" "guards" {
  input = local.placement

  lifecycle {
    precondition {
      condition     = local.isolation == "shared"
      error_message = "isolation: dedicated customers are built by the dedicated-project path, not the shared cells."
    }
    precondition {
      condition     = local.placement != null
      error_message = "No placement for ${local.group}: run the placement job first."
    }
    precondition {
      condition     = try(local.reg.inventory_clusters[local.placement.cluster].region, "") == local.region
      error_message = "Placement cluster must exist in inventory and be in the customer's region."
    }
    precondition {
      condition     = try(local.reg.inventory_sql[local.placement.sqlInstance].region, "") == local.region
      error_message = "Placement Cloud SQL instance must exist in inventory and be in the customer's region."
    }
    precondition {
      condition     = alltrue([for k, p in local.products : alltrue([for d in p.dependencies : contains(keys(local.products), d)])])
      error_message = "A product dependency is not enabled for this customer."
    }
    precondition {
      condition     = alltrue([for s in values(local.subscriptions) : local.products[s.subscriber].runtime.type == "cloud-run"])
      error_message = "Pub/Sub subscriptions are valid only for Cloud Run products."
    }
    precondition {
      condition     = alltrue([for s in values(local.subscriptions) : contains(keys(local.topics), s.topic)])
      error_message = "A subscription references a topic that no enabled product publishes."
    }
    precondition {
      condition     = alltrue([for k, p in local.products : !p.pv || p.runtime.type == "gke"])
      error_message = "Persistent volumes are valid only for approved GKE products."
    }
    precondition {
      condition     = alltrue([for k, p in local.products : p.version != null])
      error_message = "Every enabled product needs a version pin for this environment."
    }
  }
}

# ------------------------------------------------------------------ identity

resource "google_service_account" "env" {
  project      = local.compute_project
  account_id   = "${local.c}-${local.env}"
  display_name = "${local.c} ${local.env}"
  description  = "Customer environment identity: Cloud SQL login, Cloud Run and MIG runtime (managed-by terraform)"
}

# GKE pods impersonate the env GSA for Cloud SQL IAM login and signed URLs (verification V6).
resource "google_service_account_iam_member" "workload_identity" {
  for_each = local.gke

  service_account_id = google_service_account.env.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${local.workload_pool}[${local.namespace}/${each.value.short}]"
}

# Application-level envelope encryption with the customer key (decisions #6).
resource "google_kms_crypto_key_iam_member" "app_key" {
  for_each = merge(
    { env = local.gsa_member },
    { for k, p in local.gke : k => local.member[k] },
  )

  crypto_key_id = local.app_key
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value
}

# MIG VMs write logs and metrics (allowlisted project-level grants, architecture §2).
resource "google_project_iam_member" "mig_observability" {
  for_each = length(local.mig) > 0 ? toset(["roles/logging.logWriter", "roles/monitoring.metricWriter"]) : toset([])

  project = local.compute_project
  role    = each.value
  member  = "serviceAccount:${google_service_account.env.email}"
}

# ------------------------------------------------------------------ data

module "database" {
  source = "../cloud-sql-database"

  project_id            = local.data_project
  instance              = local.placement.sqlInstance
  database              = local.database
  login_service_account = google_service_account.env.email

  depends_on = [terraform_data.guards]
}

module "bucket" {
  source   = "../storage"
  for_each = local.buckets

  project_id      = local.data_project
  name            = each.value
  location        = local.is_prod ? local.multi : local.region
  dual_region     = local.is_prod ? [local.region, local.pair] : []
  kms_key         = local.is_prod ? local.data_key.multi : local.data_key.region
  iam             = [{ role = "roles/storage.objectAdmin", member = local.member[each.key] }]
  labels          = local.labels["${local.products[each.key].short}/primary"]
  deletion_policy = local.deletion[each.key]
}

module "dataset" {
  source   = "../bigquery"
  for_each = local.datasets

  project_id = local.data_project
  dataset_id = each.value
  location   = local.region
  kms_key    = local.data_key.region
  iam        = [{ role = "roles/bigquery.dataEditor", member = local.member[each.key] }]
  dr = local.is_prod ? {
    location       = local.pair
    kms_key        = local.data_key.pair
    transfer_agent = "bq-dr-copy@${local.data_project}.iam.gserviceaccount.com"
  } : null
  labels          = local.labels["${local.products[each.key].short}/primary"]
  deletion_policy = local.deletion[each.key]
}

module "topic" {
  source   = "../pubsub"
  for_each = local.topics

  project_id     = local.data_project
  project_number = local.data_number
  name           = each.value.name
  regions        = local.is_prod ? [local.region, local.pair] : [local.region]
  kms_key        = local.data_key.region
  publishers     = [local.member[each.value.product]]
  subscriptions = {
    for name, s in local.subscriptions : name => {
      push_endpoint        = module.cloud_run[s.subscriber].uri
      oidc_service_account = google_service_account.env.email
    } if s.topic == each.key
  }
  labels = local.labels["${local.products[each.value.product].short}/primary"]
}

# ------------------------------------------------------------------ runtimes

module "cloud_run" {
  source   = "../cloud-run-service"
  for_each = local.run

  project_id      = local.compute_project
  name            = "${local.c}-${each.value.short}-${local.env}"
  region          = local.region
  service_account = google_service_account.env.email
  port            = try(each.value.runtime.port, 8080)
  cpu             = try(each.value.sizing.cpu, "1")
  memory          = try(each.value.sizing.memory, "512Mi")
  min_instances   = try(each.value.sizing.minInstances, 0)
  max_instances   = try(each.value.sizing.maxInstances, 10)
  network         = local.network
  subnetwork      = "projects/${local.host_project}/regions/${local.region}/subnetworks/snet-run-${local.region}"
  network_tags    = concat([local.tenant_tag], each.value.egress ? ["egress-internet"] : [])
  invokers        = contains(local.subscribers, each.key) ? [local.gsa_member] : []
  env = merge(local.common_env, {
    PRODUCT   = each.value.short
    DB_SCHEMA = each.value.short
    BUCKET    = try(local.buckets[each.key], "")
    DATASET   = try(local.datasets[each.key], "")
  })
  labels = local.labels["${each.value.short}/primary"]

  depends_on = [terraform_data.guards]
}

module "cloud_run_dr" {
  source   = "../cloud-run-service"
  for_each = local.is_prod ? local.run : {}

  project_id      = local.compute_project
  name            = "${local.c}-${each.value.short}-${local.env}"
  region          = local.pair
  service_account = google_service_account.env.email
  port            = try(each.value.runtime.port, 8080)
  cpu             = try(each.value.sizing.cpu, "1")
  memory          = try(each.value.sizing.memory, "512Mi")
  min_instances   = local.hot_standby ? try(each.value.sizing.minInstances, 0) : 0
  max_instances   = try(each.value.sizing.maxInstances, 10)
  network         = local.network
  subnetwork      = "projects/${local.host_project}/regions/${local.pair}/subnetworks/snet-run-${local.pair}"
  network_tags    = concat([local.tenant_tag], each.value.egress ? ["egress-internet"] : [])
  invokers        = contains(local.subscribers, each.key) ? [local.gsa_member] : []
  migration_job   = false
  env = merge(local.common_env, {
    PRODUCT   = each.value.short
    DB_SCHEMA = each.value.short
    BUCKET    = try(local.buckets[each.key], "")
    DATASET   = try(local.datasets[each.key], "")
  })
  labels = local.labels["${each.value.short}/dr"]
}

module "mig" {
  source   = "../mig-service"
  for_each = local.mig

  project_id        = local.compute_project
  name              = "${local.c}-${each.value.short}-${local.env}"
  region            = local.region
  zones             = local.zones
  service_account   = google_service_account.env.email
  machine_type      = each.value.sizing.machineType
  source_image      = "projects/${local.platform_project}/global/images/family/${each.value.runtime.imageFamily}"
  subnetwork        = "projects/${local.host_project}/regions/${local.region}/subnetworks/snet-mig-${local.region}"
  network_tags      = concat([local.tenant_tag], each.value.egress ? ["egress-internet"] : [])
  port              = try(each.value.runtime.port, 8443)
  health_check_path = try(each.value.runtime.healthCheckPath, "/healthz/ready")
  min_replicas      = each.value.sizing.minReplicas
  max_replicas      = each.value.sizing.maxReplicas
  metadata = {
    customer    = local.c
    environment = local.env
    product     = each.value.short
    db-instance = local.common_env.DB_INSTANCE
    db-name     = local.database
    db-schema   = each.value.short
    app-version = each.value.version
  }
  labels = local.labels["${each.value.short}/primary"]

  depends_on = [terraform_data.guards]
}

module "mig_dr" {
  source   = "../mig-service"
  for_each = local.is_prod ? local.mig : {}

  project_id        = local.compute_project
  name              = "${local.c}-${each.value.short}-${local.env}"
  region            = local.pair
  zones             = local.pair_zones
  service_account   = google_service_account.env.email
  machine_type      = each.value.sizing.machineType
  source_image      = "projects/${local.platform_project}/global/images/family/${each.value.runtime.imageFamily}"
  subnetwork        = "projects/${local.host_project}/regions/${local.pair}/subnetworks/snet-mig-${local.pair}"
  network_tags      = concat([local.tenant_tag], each.value.egress ? ["egress-internet"] : [])
  port              = try(each.value.runtime.port, 8443)
  health_check_path = try(each.value.runtime.healthCheckPath, "/healthz/ready")
  min_replicas      = local.hot_standby ? each.value.sizing.minReplicas : 1
  max_replicas      = each.value.sizing.maxReplicas
  metadata = {
    customer    = local.c
    environment = local.env
    product     = each.value.short
    db-instance = local.common_env.DB_INSTANCE
    db-name     = local.database
    db-schema   = each.value.short
    app-version = each.value.version
  }
  labels = local.labels["${each.value.short}/dr"]
}

# ------------------------------------------------------------------ Backup for GKE (per namespace)

module "backup_plan" {
  source = "../backup-plan"
  count  = length(local.gke) > 0 ? 1 : 0

  project_id = local.compute_project
  name       = "bp-${local.namespace}"
  location   = local.is_prod ? local.pair : local.region
  cluster_id = "projects/${local.compute_project}/locations/${local.group == "devstage" ? local.zones[0] : local.region}/clusters/${local.placement.cluster}"
  namespaces = [local.namespace]
  kms_key    = local.is_prod ? local.data_key.pair : local.data_key.region
  labels     = local.labels["platform/primary"]

  depends_on = [terraform_data.guards]
}
