# L1 platform tooling for one side (architecture §2, §14, §15): management cluster, Artifact
# Registry, Binary Authorization (attestor + signing key + per-compute-project policy), platform
# service accounts with least-privilege IAM, managed Istio (fleet default), and side-specific
# security baselines (prod: central audit log bucket; non-prod: private CA for *.platform.internal).

module "registry" {
  source    = "../registry"
  repo_root = var.repo_root
}

locals {
  reg      = module.registry
  side     = var.side
  prod     = local.side == "prod"
  hub      = local.reg.platform.hubRegion
  platform = local.reg.projects["platform-${local.side}"]
  security = local.reg.projects["security-${local.side}"]
  data     = local.reg.projects["data-${local.side}"]
  host     = local.reg.projects["net-${local.side}"]
  network  = "projects/${local.host}/global/networks/vpc-${local.side}"
  groups   = { for g, cfg in local.reg.platform.groups : g => cfg if cfg.side == local.side }
  computes = { for g, cfg in local.groups : cfg.computeProject => local.reg.projects[cfg.computeProject] }
  mgmt     = local.reg.cluster_plan["mgmt-${local.side}"]

  service_numbers = merge(
    { for k in keys(local.computes) : k => local.reg.project_numbers[k] },
    { "platform-${local.side}" = local.reg.project_numbers["platform-${local.side}"] },
  )

  attestor = local.prod ? "promoted" : "built-and-signed"
}

module "labels" {
  source = "../labels"

  environment = local.prod ? "prod" : "shared"
  env_group   = local.prod ? "prod" : "shared"
}

# ------------------------------------------------------------------ Shared VPC host grants for GKE

resource "google_project_iam_member" "gke_host_agent" {
  for_each = {
    for pair in setproduct(keys(local.service_numbers), ["roles/container.hostServiceAgentUser", "roles/compute.securityAdmin"]) :
    "${pair[0]}/${pair[1]}" => { number = local.service_numbers[pair[0]], role = pair[1] }
  }

  project = local.host
  role    = each.value.role
  member  = "serviceAccount:service-${each.value.number}@container-engine-robot.iam.gserviceaccount.com"
}

# ------------------------------------------------------------------ service accounts

resource "google_service_account" "gke_nodes" {
  for_each = merge(local.computes, { "platform-${local.side}" = local.platform })

  project      = each.value
  account_id   = "gke-nodes"
  display_name = "GKE node service account"
}

resource "google_project_iam_member" "gke_nodes" {
  for_each = {
    for pair in setproduct(keys(google_service_account.gke_nodes), [
      "roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/monitoring.viewer",
      "roles/stackdriver.resourceMetadata.writer", "roles/autoscaling.metricsWriter",
    ]) : "${pair[0]}/${pair[1]}" => { key = pair[0], role = pair[1] }
  }

  project = google_service_account.gke_nodes[each.value.key].project
  role    = each.value.role
  member  = google_service_account.gke_nodes[each.value.key].member
}

resource "google_service_account" "argocd" {
  for_each = local.groups

  project      = local.platform
  account_id   = "argocd-${each.key}"
  display_name = "ArgoCD ${each.key} instance"
}

# Decisions #22: the instance reaches its group's clusters through the DNS endpoint, authorized by
# IAM on that group's compute project only. Non-prod instances hold no role on prod.
resource "google_project_iam_member" "argocd_cluster_admin" {
  for_each = local.groups

  project = local.reg.projects[each.value.computeProject]
  role    = "roles/container.admin"
  member  = google_service_account.argocd[each.key].member
}

resource "google_service_account_iam_member" "argocd_workload_identity" {
  for_each = {
    for pair in setproduct(keys(local.groups), ["argocd-application-controller", "argocd-server", "argocd-applicationset-controller"]) :
    "${pair[0]}/${pair[1]}" => { group = pair[0], ksa = pair[1] }
  }

  service_account_id = google_service_account.argocd[each.value.group].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${local.platform}.svc.id.goog[argocd-${each.value.group}/${each.value.ksa}]"
}

resource "google_service_account" "db_bootstrap" {
  project      = local.data
  account_id   = "db-bootstrap"
  display_name = "Database bootstrap job (IAM login with cloudsqlsuperuser)"
}

resource "google_project_iam_member" "db_bootstrap" {
  for_each = toset(["roles/cloudsql.client", "roles/cloudsql.instanceUser"])

  project = local.data
  role    = each.value
  member  = google_service_account.db_bootstrap.member
}

resource "google_service_account" "seed" {
  project      = local.data
  account_id   = local.prod ? "seed-publisher" : "seed-import"
  display_name = local.prod ? "Seed-down publisher (prod side)" : "Seed-down importer (non-prod side)"
}

resource "google_project_iam_member" "seed" {
  for_each = toset(local.prod ? ["roles/cloudsql.admin", "roles/cloudsql.client"] : ["roles/cloudsql.admin"])

  project = local.data
  role    = each.value
  member  = google_service_account.seed.member
}

resource "google_service_account" "bq_dr_copy" {
  count = local.prod ? 1 : 0

  project      = local.data
  account_id   = "bq-dr-copy"
  display_name = "BigQuery cross-region DR copy"
}

resource "google_project_iam_member" "bq_dr_copy" {
  count = local.prod ? 1 : 0

  project = local.data
  role    = "roles/bigquery.dataEditor"
  member  = google_service_account.bq_dr_copy[0].member
}

# Image builders (non-prod) and the promoter (prod, the only cross-perimeter reader).
resource "google_service_account" "ci" {
  project      = local.platform
  account_id   = local.prod ? "promoter" : "ci-builder"
  display_name = local.prod ? "Image promotion by digest (prod pool)" : "Image build, scan and sign (non-prod pools)"
}

# ------------------------------------------------------------------ Artifact Registry

resource "google_artifact_registry_repository" "this" {
  for_each = toset(["products", "platform"])

  project       = local.platform
  location      = local.prod ? local.reg.regions[local.hub].multiRegion : local.hub
  repository_id = each.value
  format        = "DOCKER"
  description   = local.prod ? "Promoted images only (by digest)" : "Build target for GitHub and Bitbucket pipelines"
  labels        = module.labels.labels

  docker_config {
    immutable_tags = true
  }
}

resource "google_artifact_registry_repository_iam_member" "writer" {
  for_each = google_artifact_registry_repository.this

  project    = local.platform
  location   = each.value.location
  repository = each.value.name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.ci.member
}

resource "google_artifact_registry_repository_iam_member" "node_reader" {
  for_each = {
    for pair in setproduct(keys(google_artifact_registry_repository.this), keys(google_service_account.gke_nodes)) :
    "${pair[0]}/${pair[1]}" => { repo = pair[0], sa = pair[1] }
  }

  project    = local.platform
  location   = google_artifact_registry_repository.this[each.value.repo].location
  repository = google_artifact_registry_repository.this[each.value.repo].name
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.gke_nodes[each.value.sa].member
}

# ------------------------------------------------------------------ Binary Authorization

module "signing_key_ring" {
  source = "../kms"

  project_id = local.security
  name       = "kr-binauthz"
  locations  = ["global"]
  keys       = []
  labels     = module.labels.labels
}

resource "google_kms_crypto_key" "signer" {
  name            = local.attestor
  key_ring        = "projects/${local.security}/locations/global/keyRings/kr-binauthz"
  purpose         = "ASYMMETRIC_SIGN"
  labels          = module.labels.labels
  deletion_policy = "PREVENT"

  version_template {
    algorithm = "EC_SIGN_P256_SHA256"
  }

  depends_on = [module.signing_key_ring]
}

resource "google_kms_crypto_key_iam_member" "signer" {
  crypto_key_id = google_kms_crypto_key.signer.id
  role          = "roles/cloudkms.signerVerifier"
  member        = google_service_account.ci.member
}

data "google_kms_crypto_key_version" "signer" {
  crypto_key = google_kms_crypto_key.signer.id
}

resource "google_container_analysis_note" "attestor" {
  project = local.security
  name    = "${local.attestor}-note"

  attestation_authority {
    hint {
      human_readable_name = local.prod ? "Promoted to prod by digest" : "Built, scanned and signed"
    }
  }
}

resource "google_binary_authorization_attestor" "this" {
  project = local.security
  name    = local.attestor

  attestation_authority_note {
    note_reference = google_container_analysis_note.attestor.name

    public_keys {
      id = data.google_kms_crypto_key_version.signer.id
      pkix_public_key {
        public_key_pem      = data.google_kms_crypto_key_version.signer.public_key[0].pem
        signature_algorithm = data.google_kms_crypto_key_version.signer.public_key[0].algorithm
      }
    }
  }
}

resource "google_binary_authorization_attestor_iam_member" "viewer" {
  for_each = toset([for n in values(local.service_numbers) : "serviceAccount:service-${n}@gcp-sa-binaryauthorization.iam.gserviceaccount.com"])

  project  = local.security
  attestor = google_binary_authorization_attestor.this.name
  role     = "roles/binaryauthorization.attestorsVerifier"
  member   = each.value
}

resource "google_binary_authorization_policy" "this" {
  for_each = local.computes

  project                       = each.value
  global_policy_evaluation_mode = "ENABLE"

  default_admission_rule {
    evaluation_mode         = "REQUIRE_ATTESTATION"
    enforcement_mode        = "ENFORCED_BLOCK_AND_AUDIT_LOG"
    require_attestations_by = [google_binary_authorization_attestor.this.id]
  }
}

# ------------------------------------------------------------------ managed Istio (fleet default)

resource "google_gke_hub_feature" "mesh" {
  for_each = merge(local.computes, { "platform-${local.side}" = local.platform })

  project  = each.value
  name     = "servicemesh"
  location = "global"

  fleet_default_member_config {
    mesh {
      management = "MANAGEMENT_AUTOMATIC"
    }
  }
}

# ------------------------------------------------------------------ management cluster

module "mgmt_cluster" {
  source = "../gke-cluster"

  project_id           = local.platform
  project_number       = local.reg.project_numbers["platform-${local.side}"]
  host_project_id      = local.host
  network_id           = local.network
  name                 = "mgmt-${local.side}"
  region               = local.hub
  zones                = local.mgmt.zones
  release_channel      = local.prod ? "STABLE" : "REGULAR"
  node_service_account = google_service_account.gke_nodes["platform-${local.side}"].email
  ranges = {
    nodes    = local.mgmt.nodes_cidr
    pods     = local.mgmt.pods_cidr
    services = local.mgmt.services_cidr
  }
  node_pools = {
    default = { machine_type = "e2-standard-4", min_nodes = 1, max_nodes = 3 }
    runners = {
      machine_type = "e2-standard-8"
      min_nodes    = 0
      max_nodes    = 10
      taints       = [{ key = "platform.example/runners", value = "true", effect = "NO_SCHEDULE" }]
    }
  }
  labels = module.labels.labels

  depends_on = [google_project_iam_member.gke_host_agent]
}

# ------------------------------------------------------------------ side-specific baselines

resource "google_logging_project_bucket_config" "audit" {
  count = local.prod ? 1 : 0

  project          = local.security
  location         = "global"
  bucket_id        = "audit"
  retention_days   = 400
  enable_analytics = true # linked BigQuery dataset for audit analysis and SIEM export
}

resource "google_privateca_ca_pool" "internal" {
  count = local.prod ? 0 : 1

  project  = local.security
  name     = local.reg.platform.edge.internalCaPool
  location = local.hub
  tier     = "DEVOPS"
  labels   = module.labels.labels
}

resource "google_privateca_certificate_authority" "internal" {
  count = local.prod ? 0 : 1

  project                  = local.security
  pool                     = google_privateca_ca_pool.internal[0].name
  certificate_authority_id = "platform-internal-root"
  location                 = local.hub
  type                     = "SELF_SIGNED"
  lifetime                 = "315360000s"
  deletion_protection      = true
  labels                   = module.labels.labels

  config {
    subject_config {
      subject {
        organization = "Platform Example"
        common_name  = "platform.internal root CA"
      }
    }
    x509_config {
      ca_options {
        is_ca = true
      }
      key_usage {
        base_key_usage {
          cert_sign = true
          crl_sign  = true
        }
        extended_key_usage {
          server_auth = true
        }
      }
      name_constraints {
        critical            = true
        permitted_dns_names = [local.reg.platform.dns.privateZone]
      }
    }
  }

  key_spec {
    algorithm = "EC_P256_SHA256"
  }
}
