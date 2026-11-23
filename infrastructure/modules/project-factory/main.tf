# Project factory: every project gets labels, a billing link, a budget, APIs, an audit log sink
# and (optionally) a Shared VPC attachment and quota preferences (architecture §2).

resource "google_project" "this" {
  project_id          = var.project_id
  name                = var.display_name
  folder_id           = var.folder_id
  billing_account     = var.billing_account
  labels              = var.labels
  auto_create_network = false
  deletion_policy     = var.deletion_policy
}

resource "google_project_service" "this" {
  for_each = toset(var.services)

  project            = google_project.this.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_shared_vpc_host_project" "this" {
  count   = var.shared_vpc_host ? 1 : 0
  project = google_project.this.project_id

  depends_on = [google_project_service.this]
}

resource "google_compute_shared_vpc_service_project" "this" {
  count           = var.shared_vpc_host_project == null ? 0 : 1
  host_project    = var.shared_vpc_host_project
  service_project = google_project.this.project_id

  depends_on = [google_project_service.this]
}

resource "google_billing_budget" "this" {
  billing_account = var.billing_account
  display_name    = "budget-${var.project_id}"

  budget_filter {
    projects = ["projects/${google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget.currency
      units         = tostring(var.budget.amount)
    }
  }

  dynamic "threshold_rules" {
    for_each = var.budget.thresholds
    content {
      threshold_percent = threshold_rules.value
    }
  }
}

resource "google_logging_project_sink" "audit" {
  count = var.audit_log_destination == null ? 0 : 1

  project                = google_project.this.project_id
  name                   = "central-audit"
  destination            = var.audit_log_destination
  filter                 = "logName:\"cloudaudit.googleapis.com\""
  unique_writer_identity = true
}

resource "google_cloud_quotas_quota_preference" "this" {
  for_each = var.quota_preferences

  parent        = "projects/${google_project.this.project_id}"
  name          = each.key
  service       = each.value.service
  quota_id      = each.value.quota_id
  dimensions    = each.value.dimensions
  justification = each.value.justification
  contact_email = var.quota_contact_email

  quota_config {
    preferred_value = tostring(each.value.preferred_value)
  }

  depends_on = [google_project_service.this]
}
