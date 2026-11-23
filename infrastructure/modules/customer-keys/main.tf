# Per-customer key rings for one side (decisions #24): non-prod = Dev/Stage + UAT groups in
# security-nonprod; prod = Prod group in security-prod, in the region, DR pair and multi-region
# (verification V5). Service agents get encrypt/decrypt on the "-data" keys; the env GSA and KSA
# grants on the "-app" keys are made by the environment states once the identities exist.

module "registry" {
  source    = "../registry"
  repo_root = var.repo_root
}

locals {
  reg    = module.registry
  c      = var.customer
  cust   = local.reg.customers[local.c].spec
  region = local.cust.region.primary
  pair   = local.reg.regions[local.region].drPair
  multi  = local.reg.regions[local.region].multiRegion
  groups = var.side == "prod" ? ["prod"] : ["devstage", "uat"]

  rings = {
    for g in local.groups : g => {
      envs             = local.reg.platform.groups[g].environments
      security_project = local.reg.projects[local.reg.platform.groups[g].securityProject]
      data_number      = local.reg.project_numbers[local.reg.platform.groups[g].dataProject]
      compute_number   = local.reg.project_numbers[local.reg.platform.groups[g].computeProject]
      locations        = g == "prod" ? [local.region, local.pair, local.multi] : [local.region]
    }
  }
}

module "labels" {
  source   = "../labels"
  for_each = local.rings

  customer    = local.c
  environment = length(each.value.envs) == 1 ? each.value.envs[0] : "shared"
  env_group   = each.key
}

module "key_ring" {
  source   = "../kms"
  for_each = local.rings

  project_id = each.value.security_project
  name       = "kr-${local.c}-${each.key}"
  locations  = each.value.locations
  keys       = flatten([for e in each.value.envs : ["${e}-data", "${e}-app"]])
  labels     = module.labels[each.key].labels
  iam = flatten([for e in each.value.envs : [
    for m in [
      "serviceAccount:service-${each.value.data_number}@gs-project-accounts.iam.gserviceaccount.com",
      "serviceAccount:bq-${each.value.data_number}@bigquery-encryption.iam.gserviceaccount.com",
      "serviceAccount:service-${each.value.data_number}@gcp-sa-pubsub.iam.gserviceaccount.com",
      "serviceAccount:service-${each.value.compute_number}@compute-system.iam.gserviceaccount.com",
      "serviceAccount:service-${each.value.compute_number}@gcp-sa-gkebackup.iam.gserviceaccount.com",
      ] : {
      key    = "${e}-data"
      role   = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
      member = m
    }
  ]])
}

output "key_ids" {
  value = { for g, m in module.key_ring : g => m.key_ids }
}
