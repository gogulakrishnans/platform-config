# L2 composition: one region x one environment group (architecture §3, §4, §17).
# Builds the cells declared in regions.yaml (clusters + Cloud SQL instances), the prod DR clusters
# and replicas in the pair region, the side's regional network (owned by the devstage and prod
# states), platform keys, the database bootstrap job, and writes inventory/clusters|sql/*.yaml.

module "registry" {
  source    = "../registry"
  repo_root = var.repo_root
}

locals {
  reg      = module.registry
  region   = var.region
  group    = var.group
  side     = local.group == "prod" ? "prod" : "nonprod"
  gcfg     = local.reg.platform.groups[local.group]
  defaults = local.reg.platform.cellDefaults[local.group]

  compute_project  = local.reg.projects[local.gcfg.computeProject]
  compute_number   = local.reg.project_numbers[local.gcfg.computeProject]
  data_project     = local.reg.projects[local.gcfg.dataProject]
  data_number      = local.reg.project_numbers[local.gcfg.dataProject]
  security_project = local.reg.projects[local.gcfg.securityProject]
  host_project     = local.reg.projects["net-${local.side}"]
  network_id       = "projects/${local.host_project}/global/networks/vpc-${local.side}"

  # The non-prod side's shared regional pieces are owned by the devstage state.
  owns_side = local.group != "uat"

  # Clusters of this region's cells, including prod DR clusters located in the pair region.
  clusters = {
    for k, c in local.reg.cluster_plan : k => c
    if c.group == local.group && startswith(c.cell, "${local.group}-${local.region}-")
  }

  # A prod cell keeps its DR cluster at full size if any of its customers chose hot standby.
  hot_cells = toset([
    for name, cu in local.reg.customers : cu.spec.placement.prod.cluster
    if try(cu.spec.options.dr, "") == "hot-standby" && try(cu.spec.placement.prod.cluster, null) != null
  ])

  sql = {
    for k, s in local.reg.sql_plan : k => s
    if s.region == local.region && local.owns_side && (
      (local.group == "devstage" && s.side == "nonprod") || (local.group == "prod" && s.side == "prod")
    )
  }

  platform_kr = "kr-platform-${local.region}"
  key_fmt     = "projects/${local.security_project}/locations/%s/keyRings/kr-platform-%s/cryptoKeys/%s"

  side_compute_numbers = {
    for g, cfg in local.reg.platform.groups : cfg.computeProject => local.reg.project_numbers[cfg.computeProject]
    if cfg.side == local.side
  }
}

module "labels" {
  source = "../labels"

  environment = local.group == "uat" ? "uat" : (local.group == "prod" ? "prod" : "shared")
  env_group   = local.group
}

module "labels_dr" {
  source = "../labels"

  environment = "prod"
  env_group   = "prod"
  region_role = "dr"
}

# ------------------------------------------------------------------ regional network (per side)

module "network_region" {
  source = "../network-region"
  count  = local.owns_side ? 1 : 0

  project_id              = local.host_project
  network_id              = local.network_id
  network_name            = "vpc-${local.side}"
  region                  = local.region
  side                    = local.side
  ranges                  = local.reg.ip_plan[local.region][local.side]
  nat_static_ips          = local.side == "prod" ? 2 : 0
  service_project_numbers = local.side_compute_numbers
  labels                  = module.labels.labels
}

# ------------------------------------------------------------------ platform keys for this region

module "platform_keys" {
  source = "../kms"
  count  = local.owns_side ? 1 : 0

  project_id = local.security_project
  name       = local.platform_kr
  locations  = [local.region]
  keys       = local.side == "prod" ? ["sql", "gke-secrets", "seed"] : ["sql", "gke-secrets"]
  labels     = module.labels.labels
  iam = concat(
    [{ key = "sql", role = "roles/cloudkms.cryptoKeyEncrypterDecrypter", member = "serviceAccount:service-${local.data_number}@gcp-sa-cloud-sql.iam.gserviceaccount.com" }],
    [for n in values(local.side_compute_numbers) : { key = "gke-secrets", role = "roles/cloudkms.cryptoKeyEncrypterDecrypter", member = "serviceAccount:service-${n}@container-engine-robot.iam.gserviceaccount.com" }],
    local.side == "prod" ? [{ key = "seed", role = "roles/cloudkms.cryptoKeyEncrypterDecrypter", member = "serviceAccount:service-${local.data_number}@gs-project-accounts.iam.gserviceaccount.com" }] : [],
  )
}

# ------------------------------------------------------------------ clusters (cells + DR)

module "cluster" {
  source   = "../gke-cluster"
  for_each = local.clusters

  project_id           = local.compute_project
  project_number       = local.compute_number
  host_project_id      = local.host_project
  network_id           = local.network_id
  name                 = each.key
  region               = each.value.region
  zones                = each.value.zones
  cluster_type         = local.group == "devstage" ? "zonal" : "regional"
  release_channel      = local.gcfg.releaseChannel
  node_service_account = "gke-nodes@${local.compute_project}.iam.gserviceaccount.com"
  ranges = {
    nodes    = each.value.nodes_cidr
    pods     = each.value.pods_cidr
    services = each.value.services_cidr
  }
  secrets_encryption_key = format(local.key_fmt, each.value.region, each.value.region, "gke-secrets")
  node_pools = {
    default = {
      machine_type = local.defaults.machineType
      min_nodes    = each.value.role == "dr" && !contains(local.hot_cells, each.value.cell) ? local.defaults.drMinNodes : local.defaults.minNodes
      max_nodes    = local.defaults.maxNodes
    }
  }
  labels = each.value.role == "dr" ? module.labels_dr.labels : module.labels.labels

  depends_on = [module.network_region, module.platform_keys]
}

# ------------------------------------------------------------------ Cloud SQL instances

module "sql" {
  source   = "../cloud-sql-instance"
  for_each = local.sql

  project_id                = local.data_project
  name                      = each.key
  region                    = local.region
  tier                      = local.side == "prod" ? local.reg.platform.cellDefaults.prod.sqlTier : local.reg.platform.cellDefaults.devstage.sqlTier
  edition                   = local.side == "prod" ? "ENTERPRISE_PLUS" : "ENTERPRISE"
  network_id                = local.network_id
  psa_range_name            = "psa-${local.region}"
  encryption_key            = format(local.key_fmt, local.region, local.region, "sql")
  bootstrap_service_account = "db-bootstrap@${local.data_project}.iam.gserviceaccount.com"
  designate_dr_replica      = var.designate_dr_replica
  dr = each.value.dr == null ? null : {
    region         = each.value.dr.region
    encryption_key = format(local.key_fmt, each.value.dr.region, each.value.dr.region, "sql")
    psa_range_name = "psa-${each.value.dr.region}"
  }
  labels          = module.labels.labels
  deletion_policy = local.side == "prod" ? "PREVENT" : "DELETE"

  depends_on = [module.platform_keys]
}

# ------------------------------------------------------------------ database bootstrap job

resource "google_cloud_run_v2_job" "db_bootstrap" {
  count = local.owns_side ? 1 : 0

  project             = local.data_project
  name                = "db-bootstrap-${local.region}"
  location            = local.region
  labels              = module.labels.labels
  deletion_protection = false

  template {
    labels = module.labels.labels
    template {
      service_account = "db-bootstrap@${local.data_project}.iam.gserviceaccount.com"
      max_retries     = 2
      timeout         = "900s"

      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = local.network_id
          subnetwork = "projects/${local.host_project}/regions/${local.region}/subnetworks/snet-run-${local.region}"
          tags       = ["run", "platform"]
        }
      }

      containers {
        image = "${local.region}-docker.pkg.dev/${local.reg.projects["platform-${local.side}"]}/platform/db-bootstrap:${var.db_bootstrap_version}"
        env {
          name  = "DATA_PROJECT"
          value = local.data_project
        }
        env {
          name  = "REGION"
          value = local.region
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }

  depends_on = [module.network_region]
}

# ------------------------------------------------------------------ seed-down work bucket (prod)

module "seed_work_bucket" {
  source = "../storage"
  count  = local.side == "prod" ? 1 : 0

  project_id        = local.data_project
  name              = "${local.reg.platform.bucketPrefix}-seed-work-${local.region}"
  location          = local.region
  kms_key           = format(local.key_fmt, local.region, local.region, "seed")
  versioning        = false
  delete_after_days = 2
  labels            = module.labels.labels
  deletion_policy   = "DELETE"
  iam = [
    { role = "roles/storage.objectAdmin", member = "serviceAccount:seed-publisher@${local.data_project}.iam.gserviceaccount.com" },
    { role = "roles/storage.objectAdmin", member = "serviceAccount:service-${local.data_number}@gcp-sa-cloud-sql.iam.gserviceaccount.com" },
  ]

  depends_on = [module.platform_keys]
}

# ------------------------------------------------------------------ inventory written back to Git

resource "local_file" "cluster_inventory" {
  for_each = var.write_inventory ? { for k, c in local.clusters : k => c if c.role == "primary" } : {}

  filename        = "${var.repo_root}/inventory/clusters/${each.key}.yaml"
  file_permission = "0644"
  content = templatefile("${path.module}/templates/cluster.yaml.tftpl", {
    layer       = "L2-region/${local.region}/${local.group}"
    c           = each.value
    project     = local.gcfg.computeProject
    endpoint    = module.cluster[each.key].dns_endpoint
    dr          = local.group == "prod" ? local.clusters["${each.key}-dr"] : null
    dr_endpoint = local.group == "prod" ? module.cluster["${each.key}-dr"].dns_endpoint : null
    sql         = local.group == "prod" ? ["sql-prod-${trimprefix(each.key, "prod-")}"] : []
  })
}

resource "local_file" "sql_inventory" {
  for_each = var.write_inventory ? local.sql : {}

  filename        = "${var.repo_root}/inventory/sql/${each.key}.yaml"
  file_permission = "0644"
  content = templatefile("${path.module}/templates/sql.yaml.tftpl", {
    layer          = "L2-region/${local.region}/${local.group}"
    s              = each.value
    project        = local.gcfg.dataProject
    write_endpoint = module.sql[each.key].write_endpoint
  })
}
