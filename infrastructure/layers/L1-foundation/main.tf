# L1 Foundation (once): the fixed project set, Shared VPCs, org policies, VPC-SC, platform tooling
# (management clusters, registries, Binary Authorization), runner pools and the three ArgoCD
# instances. Runs on GitHub-hosted runners for the very first apply (perimeters in dry-run), then on
# the prod pool with an extra approval (architecture §17).

locals {
  repo_root = "${path.module}/../../.."
  reg       = module.registry
  plat      = local.reg.platform
  p         = local.reg.projects
  n         = local.reg.project_numbers
  hub       = local.plat.hubRegion
  repo_url  = "https://github.com/${local.plat.github.org}/${local.plat.github.repo}.git"

  # Project kind => APIs.
  services = {
    net = ["compute.googleapis.com", "container.googleapis.com", "dns.googleapis.com", "servicenetworking.googleapis.com"]
    compute = ["compute.googleapis.com", "container.googleapis.com", "run.googleapis.com", "gkehub.googleapis.com",
      "mesh.googleapis.com", "gkebackup.googleapis.com", "binaryauthorization.googleapis.com", "containeranalysis.googleapis.com",
      "certificatemanager.googleapis.com", "iap.googleapis.com", "secretmanager.googleapis.com", "cloudquotas.googleapis.com",
    "artifactregistry.googleapis.com", "iamcredentials.googleapis.com"]
    data = ["sqladmin.googleapis.com", "storage.googleapis.com", "bigquery.googleapis.com", "bigquerydatatransfer.googleapis.com",
      "pubsub.googleapis.com", "run.googleapis.com", "dns.googleapis.com", "servicenetworking.googleapis.com", "compute.googleapis.com",
    "cloudfunctions.googleapis.com", "cloudscheduler.googleapis.com", "storagetransfer.googleapis.com", "eventarc.googleapis.com"]
    exchange = ["storage.googleapis.com", "bigquery.googleapis.com", "cloudkms.googleapis.com"]
    platform = ["compute.googleapis.com", "container.googleapis.com", "artifactregistry.googleapis.com", "containerscanning.googleapis.com",
      "gkehub.googleapis.com", "mesh.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com", "cloudquotas.googleapis.com",
    "monitoring.googleapis.com", "logging.googleapis.com"]
    security = ["cloudkms.googleapis.com", "containeranalysis.googleapis.com", "binaryauthorization.googleapis.com",
    "privateca.googleapis.com", "logging.googleapis.com", "securitycenter.googleapis.com"]
  }

  projects = {
    for key, proj in local.plat.projects : key => {
      id          = proj.id
      folder      = local.plat.folders[proj.folder]
      kind        = split("-", key)[0]
      side        = proj.side
      host        = startswith(key, "net-")
      attach_to   = contains(["compute", "data", "platform"], split("-", key)[0]) && proj.side != "exchange" ? local.p["net-${proj.side}"] : null
      environment = proj.side == "prod" ? "prod" : "shared"
      env_group   = proj.side == "prod" ? "prod" : (key == "compute-uat" ? "uat" : (key == "compute-devstage" ? "devstage" : "shared"))
    }
  }

  allowed_locations = distinct(concat(
    [for r in keys(local.reg.regions) : "in:${r}-locations"],
    [for r in values(local.reg.regions) : r.multiRegion],
    ["global"],
  ))

  tf = local.plat.iac.serviceAccounts
  sa = {
    promoter       = "serviceAccount:promoter@${local.p["platform-prod"]}.iam.gserviceaccount.com"
    seed_publisher = "serviceAccount:seed-publisher@${local.p["data-prod"]}.iam.gserviceaccount.com"
    seed_import    = "serviceAccount:seed-import@${local.p["data-nonprod"]}.iam.gserviceaccount.com"
    sql_agent_prod = "serviceAccount:service-${local.n["data-prod"]}@gcp-sa-cloud-sql.iam.gserviceaccount.com"
    sql_agent_np   = "serviceAccount:service-${local.n["data-nonprod"]}@gcp-sa-cloud-sql.iam.gserviceaccount.com"
    tf_l1          = "serviceAccount:${local.tf.l1}"
    tf_prod        = "serviceAccount:${local.tf.prod}"
  }
  numbers = {
    for side in ["nonprod", "prod", "exchange"] : side => [for k, v in local.plat.projects : v.number if v.side == side]
  }
  exchange = "projects/${local.n["data-exchange"]}"
  read_storage = {
    "storage.googleapis.com"  = ["google.storage.objects.get", "google.storage.objects.list"]
    "bigquery.googleapis.com" = ["*"]
  }
}

module "registry" {
  source    = "../../modules/registry"
  repo_root = local.repo_root
}

module "labels" {
  source   = "../../modules/labels"
  for_each = local.projects

  environment = each.value.environment
  env_group   = each.value.env_group
}

# ------------------------------------------------------------------ projects (project factory)

module "project" {
  source   = "../../modules/project-factory"
  for_each = local.projects

  project_id              = each.value.id
  display_name            = each.key
  folder_id               = each.value.folder
  billing_account         = local.plat.billingAccount
  labels                  = module.labels[each.key].labels
  services                = local.services[each.value.kind]
  shared_vpc_host         = each.value.host
  shared_vpc_host_project = each.value.attach_to
  audit_log_destination   = "logging.googleapis.com/projects/${local.p["security-prod"]}/locations/global/buckets/audit"
  budget                  = { amount = try(local.plat.budgets[each.key], 2000) }
}

# Per-side Terraform identities (L0) administer only their own side's projects; the prod identity
# also administers the exchange (per-customer exchange states run on the prod pool).
locals {
  tf_roles = [
    "roles/editor", "roles/resourcemanager.projectIamAdmin", "roles/iam.serviceAccountAdmin",
    "roles/cloudkms.admin", "roles/container.admin", "roles/run.admin", "roles/compute.networkAdmin",
    "roles/certificatemanager.owner", "roles/dns.admin", "roles/cloudsql.admin", "roles/storage.admin",
    "roles/bigquery.admin", "roles/pubsub.admin", "roles/gkebackup.admin",
  ]
  tf_grants = {
    for x in flatten([for key, proj in local.projects : [
      for role in local.tf_roles : {
        key     = "${key}/${role}"
        project = proj.id
        member  = "serviceAccount:${proj.side == "nonprod" ? local.tf.nonprod : local.tf.prod}"
        role    = role
      }
    ]]) : x.key => x
  }
}

resource "google_project_iam_member" "terraform_side" {
  for_each = local.tf_grants

  project = each.value.project
  role    = each.value.role
  member  = each.value.member

  depends_on = [module.project]
}

# The Managed Prometheus query frontend on every cluster of a group (argocd/addons/platform) reads
# metrics for canary analysis. Granted to its Workload Identity principal; no GSA, no key.
resource "google_project_iam_member" "gmp_frontend" {
  for_each = local.plat.groups

  project = local.p[each.value.computeProject]
  role    = "roles/monitoring.viewer"
  member  = "principal://iam.googleapis.com/projects/${local.n[each.value.computeProject]}/locations/global/workloadIdentityPools/${local.p[each.value.computeProject]}.svc.id.goog/subject/ns/platform-system/sa/gmp-frontend"

  depends_on = [module.project]
}

module "org_policies" {
  source = "../../modules/org-policies"

  parent                 = local.plat.folders.platform
  org_id                 = local.plat.organization.id
  allowed_locations      = local.allowed_locations
  trusted_image_projects = ["projects/${local.p["platform-nonprod"]}", "projects/${local.p["platform-prod"]}"]
}

# ------------------------------------------------------------------ Shared VPCs

module "network" {
  source   = "../../modules/network"
  for_each = toset(["nonprod", "prod"])

  project_id   = local.p["net-${each.key}"]
  name         = "vpc-${each.key}"
  psa_ranges   = { for r in keys(local.reg.active_regions) : r => local.reg.ip_plan[r][each.key].psa }
  private_zone = each.key == "nonprod" ? local.plat.dns.privateZone : null
  public_zones = each.key == "prod" ? [local.plat.dns.publicZone] : [local.plat.dns.uatZone]
  labels       = module.labels["net-${each.key}"].labels

  depends_on = [module.project]
}

# The hub region's network footprint is needed by the management clusters and runners.
module "hub_network" {
  source   = "../../modules/network-region"
  for_each = toset(["nonprod", "prod"])

  project_id     = local.p["net-${each.key}"]
  network_id     = module.network[each.key].network_id
  network_name   = "vpc-${each.key}"
  region         = local.hub
  side           = each.key
  ranges         = local.reg.ip_plan[local.hub][each.key]
  nat_static_ips = each.key == "prod" ? 2 : 0
  labels         = module.labels["net-${each.key}"].labels
  service_project_numbers = {
    for k, v in local.plat.projects : k => v.number
    if v.side == each.key && (startswith(k, "compute-") || startswith(k, "platform-"))
  }
}

# ------------------------------------------------------------------ platform tooling and runners

module "platform" {
  source   = "../../modules/platform"
  for_each = toset(["nonprod", "prod"])

  repo_root = local.repo_root
  side      = each.key

  depends_on = [module.project, module.hub_network]
}

module "runner_pools" {
  source   = "../../modules/runner-pools"
  for_each = toset(["nonprod", "prod"])

  repo_root                 = local.repo_root
  side                      = each.key
  terraform_service_account = local.tf[each.key]
  ansible_image             = "projects/${local.p["platform-${each.key}"]}/global/images/family/ansible-runner"

  depends_on = [module.platform]
}

# ------------------------------------------------------------------ VPC Service Controls

module "vpc_sc" {
  source = "../../modules/vpc-sc"

  access_policy = local.plat.accessPolicy
  enforce       = var.enforce_vpc_sc
  perimeters = {
    nonprod = {
      project_numbers = local.numbers.nonprod
      ingress = [
        { title = "L1 foundation", identities = [local.sa.tf_l1], sources = ["projects/${local.n["platform-prod"]}"], resources = ["*"], services = { "*" = ["*"] } },
        { title = "Promotion reads the non-prod registry and images", identities = [local.sa.promoter], sources = ["projects/${local.n["platform-prod"]}"],
        resources = ["projects/${local.n["platform-nonprod"]}"], services = { "artifactregistry.googleapis.com" = ["*"], "compute.googleapis.com" = ["*"] } },
      ]
      egress = [
        { title = "Read own shared reference", identity_type = "ANY_SERVICE_ACCOUNT", resources = [local.exchange], services = local.read_storage },
        { title = "Seed import", identities = [local.sa.seed_import, local.sa.sql_agent_np], resources = [local.exchange], services = { "storage.googleapis.com" = ["google.storage.objects.get"] } },
      ]
    }
    prod = {
      project_numbers = local.numbers.prod
      egress = [
        { title = "L1 foundation", identities = [local.sa.tf_l1], resources = ["*"], services = { "*" = ["*"] } },
        { title = "Exchange administration (prod pool Terraform)", identities = [local.sa.tf_prod], resources = [local.exchange], services = { "*" = ["*"] } },
        { title = "Read own shared reference", identity_type = "ANY_SERVICE_ACCOUNT", resources = [local.exchange], services = local.read_storage },
        { title = "Publish seed dumps", identities = [local.sa.seed_publisher, local.sa.sql_agent_prod], resources = [local.exchange], services = { "storage.googleapis.com" = ["google.storage.objects.create"] } },
        { title = "Promote shared reference", identities = [local.sa.promoter], resources = [local.exchange], services = { "storage.googleapis.com" = ["*"], "bigquery.googleapis.com" = ["*"] } },
        { title = "Promotion reads the non-prod registry and images", identities = [local.sa.promoter], resources = ["projects/${local.n["platform-nonprod"]}"],
        services = { "artifactregistry.googleapis.com" = ["*"], "compute.googleapis.com" = ["*"] } },
      ]
    }
    exchange = {
      project_numbers = local.numbers.exchange
      ingress = [
        { title = "L1 foundation and exchange administration", identities = [local.sa.tf_l1, local.sa.tf_prod], sources = ["projects/${local.n["platform-prod"]}"], resources = ["*"], services = { "*" = ["*"] } },
        { title = "Prod and non-prod workloads read shared reference", identity_type = "ANY_SERVICE_ACCOUNT",
        sources = [for x in concat(local.numbers.prod, local.numbers.nonprod) : "projects/${x}"], resources = ["*"], services = local.read_storage },
        { title = "Seed publish", identities = [local.sa.seed_publisher, local.sa.sql_agent_prod], sources = ["projects/${local.n["data-prod"]}"], resources = ["*"],
        services = { "storage.googleapis.com" = ["google.storage.objects.create"] } },
        { title = "Promote shared reference", identities = [local.sa.promoter], sources = ["projects/${local.n["platform-prod"]}"], resources = ["*"],
        services = { "storage.googleapis.com" = ["*"], "bigquery.googleapis.com" = ["*"] } },
        { title = "Seed import", identities = [local.sa.seed_import, local.sa.sql_agent_np], sources = ["projects/${local.n["data-nonprod"]}"], resources = ["*"],
        services = { "storage.googleapis.com" = ["google.storage.objects.get"] } },
      ]
    }
  }

  depends_on = [module.project]
}

# ------------------------------------------------------------------ ArgoCD (the only Terraform -> cluster step, C17)

data "google_client_config" "this" {}

resource "helm_release" "argocd_nonprod" {
  for_each = toset(["devstage", "uat"])
  provider = helm.nonprod

  name             = "argocd-${each.key}"
  namespace        = "argocd-${each.key}"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.argocd_chart_version
  values = [templatefile("${path.module}/argocd-values.yaml.tftpl", {
    group           = each.key
    service_account = module.platform["nonprod"].argocd_service_accounts[each.key]
    install_crds    = each.key == "devstage"
    repo_url        = local.repo_url
    appset_policy   = "sync"
    root_prune      = true
  })]
}

resource "helm_release" "argocd_prod" {
  provider = helm.prod

  name             = "argocd-prod"
  namespace        = "argocd-prod"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.argocd_chart_version
  values = [templatefile("${path.module}/argocd-values.yaml.tftpl", {
    group           = "prod"
    service_account = module.platform["prod"].argocd_service_accounts["prod"]
    install_crds    = true
    repo_url        = local.repo_url
    appset_policy   = "create-update" # never delete Applications from a generator in prod
    root_prune      = false
  })]
}
