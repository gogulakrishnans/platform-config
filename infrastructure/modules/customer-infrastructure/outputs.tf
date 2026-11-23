output "bootstrap" {
  description = "Input for the database bootstrap job, run by the pipeline right after apply (architecture §8)."
  value = {
    project  = local.data_project
    region   = local.region
    instance = local.placement.sqlInstance
    database = local.database
    login    = trimsuffix(local.gsa_email, ".gserviceaccount.com")
    schemas  = local.schemas
  }
}

output "service_account" {
  value = google_service_account.env.email
}

output "namespace" {
  value = local.namespace
}

output "kubernetes_service_accounts" {
  description = "GKE products => KSA name (rendered by the tenant chart, bound via WIF)."
  value       = { for k, p in local.gke : k => p.short }
}

output "buckets" {
  value = local.buckets
}

output "datasets" {
  value = local.datasets
}

output "topics" {
  value = { for k, t in local.topics : k => t.name }
}

output "subscriptions" {
  value = keys(local.subscriptions)
}

output "cloud_run_services" {
  value = { for k, m in module.cloud_run : k => m.name }
}

output "migs" {
  value = { for k, p in local.mig : k => "${local.c}-${p.short}-${local.env}" }
}

output "labels" {
  value = local.labels
}
