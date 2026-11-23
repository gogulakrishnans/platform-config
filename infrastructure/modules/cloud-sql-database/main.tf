# One customer database per environment on a pooled instance, plus the customer's environment login
# (IAM service-account user). Grants and product schemas are applied by the database bootstrap job,
# never by Terraform (architecture §8).

variable "project_id" {
  description = "Data project that holds the instance."
  type        = string
}

variable "instance" {
  type = string
}

variable "database" {
  description = "Database name, {customer}_{env} with hyphens replaced by underscores."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9_]{1,62}$", var.database))
    error_message = "database must be a valid PostgreSQL identifier."
  }
}

variable "login_service_account" {
  description = "Email of the customer environment GSA."
  type        = string
}

variable "deletion_policy" {
  type    = string
  default = "ABANDON"
}

locals {
  iam_user = trimsuffix(var.login_service_account, ".gserviceaccount.com")
  # The two allowlisted project-level grants, limited to this instance (decisions: architecture §2).
  condition = "resource.name == \"projects/${var.project_id}/instances/${var.instance}\" && resource.service == \"sqladmin.googleapis.com\""
}

resource "google_sql_database" "this" {
  project         = var.project_id
  instance        = var.instance
  name            = var.database
  deletion_policy = var.deletion_policy
}

resource "google_sql_user" "login" {
  project  = var.project_id
  instance = var.instance
  name     = local.iam_user
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_project_iam_member" "sql_access" {
  for_each = toset(["roles/cloudsql.client", "roles/cloudsql.instanceUser"])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.login_service_account}"

  condition {
    title       = "only-${var.instance}"
    description = "Customer login limited to its Cloud SQL instance"
    expression  = local.condition
  }
}

output "database" {
  value = google_sql_database.this.name
}

output "iam_user" {
  value = google_sql_user.login.name
}
