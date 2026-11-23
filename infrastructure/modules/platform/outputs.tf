output "mgmt_cluster" {
  value = {
    id       = module.mgmt_cluster.id
    name     = module.mgmt_cluster.name
    location = module.mgmt_cluster.location
    endpoint = module.mgmt_cluster.dns_endpoint
  }
}

output "argocd_service_accounts" {
  value = { for g, sa in google_service_account.argocd : g => sa.email }
}

output "ci_service_account" {
  value = google_service_account.ci.email
}

output "registries" {
  value = { for k, r in google_artifact_registry_repository.this : k => r.registry_uri }
}

output "attestor" {
  value = google_binary_authorization_attestor.this.id
}

output "audit_log_bucket" {
  value = try("logging.googleapis.com/projects/${local.security}/locations/global/buckets/audit", null)
}
