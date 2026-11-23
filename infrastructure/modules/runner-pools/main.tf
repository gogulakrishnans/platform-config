# Shared CI and Ansible runner pools for one side (architecture §15). The runner controllers
# (Actions Runner Controller, Bitbucket runner) are installed by ArgoCD on the management cluster's
# tainted "runners" node pool; this module creates their identities and the Ansible runner MIG.
# All runners are ephemeral, keyless (Workload Identity / WIF) and have no public IP.

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
  host     = local.reg.projects["net-${local.side}"]
  pool     = "${local.platform}.svc.id.goog"
  computes = { for g, cfg in local.reg.platform.groups : cfg.computeProject => local.reg.projects[cfg.computeProject] if cfg.side == local.side }

  # Runner KSA (namespace/name) => service account it may impersonate. Terraform runs as the L0
  # service account of its side; build and promotion jobs use narrower identities.
  impersonation = merge(
    { "arc-runners/terraform" = var.terraform_service_account },
    local.prod ? {
      "arc-runners/promoter" = "promoter@${local.platform}.iam.gserviceaccount.com"
      "arc-runners/deployer" = google_service_account.deployer[0].email
      } : {
      "arc-runners/builder"       = "ci-builder@${local.platform}.iam.gserviceaccount.com"
      "bitbucket-runners/builder" = "ci-builder@${local.platform}.iam.gserviceaccount.com"
    },
  )
}

module "labels" {
  source = "../labels"

  environment = local.prod ? "prod" : "shared"
  env_group   = local.prod ? "prod" : "shared"
}

resource "google_service_account_iam_member" "runner_impersonation" {
  for_each = local.impersonation

  service_account_id = "projects/-/serviceAccounts/${each.value}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${local.pool}[${each.key}]"
}

# Prod deploy steps (Cloud Run revisions, MIG templates) run as a narrow deployer identity.
resource "google_service_account" "deployer" {
  count = local.prod ? 1 : 0

  project      = local.platform
  account_id   = "deployer"
  display_name = "Cloud Run and MIG deploy steps (prod pool)"
}

resource "google_project_iam_member" "deployer" {
  for_each = local.prod ? {
    for pair in setproduct(keys(local.computes), ["roles/run.developer", "roles/compute.instanceAdmin.v1", "roles/iam.serviceAccountUser"]) :
    "${pair[0]}/${pair[1]}" => { project = local.computes[pair[0]], role = pair[1] }
  } : {}

  project = each.value.project
  role    = each.value.role
  member  = google_service_account.deployer[0].member
}

# ------------------------------------------------------------------ Ansible runners

resource "google_service_account" "ansible" {
  project      = local.platform
  account_id   = "ansible-${local.side}"
  display_name = "Ansible runners (${local.side})"
}

resource "google_project_iam_member" "ansible" {
  for_each = {
    for pair in setproduct(keys(local.computes), ["roles/compute.osAdminLogin", "roles/compute.viewer", "roles/iap.tunnelResourceAccessor"]) :
    "${pair[0]}/${pair[1]}" => { project = local.computes[pair[0]], role = pair[1] }
  }

  project = each.value.project
  role    = each.value.role
  member  = google_service_account.ansible.member
}

resource "google_compute_region_instance_template" "ansible" {
  project      = local.platform
  name_prefix  = "ansible-${local.side}-"
  region       = local.hub
  machine_type = "e2-standard-2"
  labels       = module.labels.labels
  tags         = ["ops", "ansible-runner"]

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
  }

  disk {
    source_image = var.ansible_image
    boot         = true
    auto_delete  = true
    disk_type    = "pd-balanced"
    disk_size_gb = 30
  }

  network_interface {
    subnetwork = "projects/${local.host}/regions/${local.hub}/subnetworks/snet-ops-${local.hub}"
  }

  service_account {
    email  = google_service_account.ansible.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_region_instance_group_manager" "ansible" {
  project                   = local.platform
  name                      = "ansible-${local.side}"
  region                    = local.hub
  base_instance_name        = "ansible-${local.side}"
  target_size               = var.ansible_runners
  distribution_policy_zones = local.reg.regions[local.hub].zones

  version {
    instance_template = google_compute_region_instance_template.ansible.self_link
  }

  update_policy {
    type                  = "PROACTIVE"
    minimal_action        = "REPLACE"
    max_surge_fixed       = 3
    max_unavailable_fixed = 0
  }
}

output "ansible_service_account" {
  value = google_service_account.ansible.email
}

output "runner_identities" {
  value = local.impersonation
}
