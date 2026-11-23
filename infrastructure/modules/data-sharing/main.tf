# Per-customer exchange resources and data-sharing grants (architecture §9). Runs after the four
# environment states (it grants to their identities) on the prod pool, which administers the
# exchange perimeter. Terraform turns data-sharing.yaml into IAM; the isolation tests assert it.

module "registry" {
  source    = "../registry"
  repo_root = var.repo_root
}

locals {
  reg    = module.registry
  c      = var.customer
  c_     = replace(var.customer, "-", "_")
  cust   = local.reg.customers[local.c].spec
  policy = local.reg.data_sharing[local.c]
  region = local.cust.region.primary
  prefix = local.reg.platform.bucketPrefix

  exchange_project = local.reg.projects["data-exchange"]
  exchange_number  = local.reg.project_numbers["data-exchange"]

  shared_reference = try(local.policy.sharedReference, false)
  promote_up       = try(local.policy.promoteUp.enabled, false)
  seed_targets     = try(local.policy.seedDown.targets, [])
  seed_down        = length(local.seed_targets) > 0

  # Every environment identity of this customer: the env GSA and the GKE namespace principal set.
  readers = flatten([for env, e in local.reg.envs : [
    "serviceAccount:${local.c}-${env}@${local.reg.projects[local.reg.platform.groups[e.group].computeProject]}.iam.gserviceaccount.com",
    "principalSet://iam.googleapis.com/projects/${local.reg.project_numbers[local.reg.platform.groups[e.group].computeProject]}/locations/global/workloadIdentityPools/${local.reg.projects[local.reg.platform.groups[e.group].computeProject]}.svc.id.goog/namespace/${local.c}-${env}",
  ]])
  promoter       = "serviceAccount:promoter@${local.reg.projects["platform-prod"]}.iam.gserviceaccount.com"
  seed_publisher = "serviceAccount:seed-publisher@${local.reg.projects["data-prod"]}.iam.gserviceaccount.com"
  seed_importer  = "serviceAccount:seed-import@${local.reg.projects["data-nonprod"]}.iam.gserviceaccount.com"
  sql_agent_prod = "serviceAccount:service-${local.reg.project_numbers["data-prod"]}@gcp-sa-cloud-sql.iam.gserviceaccount.com"
  sql_agent_np   = "serviceAccount:service-${local.reg.project_numbers["data-nonprod"]}@gcp-sa-cloud-sql.iam.gserviceaccount.com"

  key = "projects/${local.exchange_project}/locations/${local.region}/keyRings/kr-${local.c}-exchange/cryptoKeys/data"

  products_without_export = [for p in keys(local.reg.customer_products[local.c]) : p if !try(local.reg.products[p].spec.supportsExport, false)]
}

module "labels" {
  source = "../labels"

  customer    = local.c
  environment = "shared"
  env_group   = "shared"
}

resource "terraform_data" "policy_guards" {
  input = local.policy

  lifecycle {
    precondition {
      condition     = alltrue([for t in local.seed_targets : contains(["dev", "stage", "uat"], t)])
      error_message = "seedDown.targets may only contain dev, stage or uat."
    }
    precondition {
      condition     = !local.seed_down || try(local.policy.seedDown.mode, "") == "sanitized"
      error_message = "seedDown.mode must be sanitized: nothing leaves prod unsanitized."
    }
    precondition {
      condition     = !local.promote_up || length(local.products_without_export) == 0
      error_message = "promoteUp needs config export/import in every enabled product."
    }
  }
}

module "exchange_key" {
  source = "../kms"

  project_id = local.exchange_project
  name       = "kr-${local.c}-exchange"
  locations  = [local.region]
  keys       = ["data"]
  labels     = module.labels.labels
  iam = [for m in [
    "serviceAccount:service-${local.exchange_number}@gs-project-accounts.iam.gserviceaccount.com",
    "serviceAccount:bq-${local.exchange_number}@bigquery-encryption.iam.gserviceaccount.com",
    ] : {
    key    = "data"
    role   = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
    member = m
  }]
}

module "shared_bucket" {
  source = "../storage"

  project_id = local.exchange_project
  name       = "${local.prefix}-${local.c}-shared"
  location   = local.region
  kms_key    = local.key
  labels     = module.labels.labels
  iam = concat(
    local.shared_reference ? [for r in local.readers : { role = "roles/storage.objectViewer", member = r }] : [],
    local.shared_reference ? [{ role = "roles/storage.objectAdmin", member = local.promoter }] : [],
  )

  depends_on = [module.exchange_key]
}

module "shared_dataset" {
  source = "../bigquery"

  project_id = local.exchange_project
  dataset_id = "${local.c_}_shared"
  location   = local.region
  kms_key    = local.key
  labels     = module.labels.labels
  iam = concat(
    local.shared_reference ? [for r in local.readers : { role = "roles/bigquery.dataViewer", member = r }] : [],
    local.shared_reference ? [{ role = "roles/bigquery.dataEditor", member = local.promoter }] : [],
  )

  depends_on = [module.exchange_key]
}

module "seed_bucket" {
  source = "../storage"
  count  = local.seed_down ? 1 : 0

  project_id        = local.exchange_project
  name              = "${local.prefix}-${local.c}-seed"
  location          = local.region
  kms_key           = local.key
  versioning        = false
  delete_after_days = 7
  labels            = module.labels.labels
  deletion_policy   = "DELETE"
  iam = [
    { role = "roles/storage.objectCreator", member = local.seed_publisher },
    { role = "roles/storage.objectCreator", member = local.sql_agent_prod },
    { role = "roles/storage.objectViewer", member = local.seed_importer },
    { role = "roles/storage.objectViewer", member = local.sql_agent_np },
  ]

  depends_on = [module.exchange_key, terraform_data.policy_guards]
}

output "shared_bucket" {
  value = module.shared_bucket.name
}

output "shared_dataset" {
  value = module.shared_dataset.dataset_id
}

output "seed_bucket" {
  value = try(module.seed_bucket[0].name, null)
}

output "readers" {
  value = local.shared_reference ? local.readers : []
}
