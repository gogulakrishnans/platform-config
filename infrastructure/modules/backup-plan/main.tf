# Backup for GKE plan per customer namespace (architecture §8): a single customer can be restored.
# Prod plans are located in the DR pair region so backups survive a region loss.

variable "project_id" {
  type = string
}

variable "name" {
  type = string
}

variable "location" {
  description = "Plan (and backup storage) location. Prod: the DR pair region."
  type        = string
}

variable "cluster_id" {
  description = "projects/P/locations/L/clusters/C"
  type        = string
}

variable "namespaces" {
  type = list(string)
}

variable "kms_key" {
  description = "Customer key in the plan location."
  type        = string
}

variable "retain_days" {
  type    = number
  default = 14
}

variable "cron" {
  type    = string
  default = "15 2 * * *"
}

variable "labels" {
  type = map(string)
}

resource "google_gke_backup_backup_plan" "this" {
  project  = var.project_id
  name     = var.name
  location = var.location
  cluster  = var.cluster_id
  labels   = var.labels

  backup_config {
    include_volume_data = true
    include_secrets     = true

    selected_namespaces {
      namespaces = var.namespaces
    }

    encryption_key {
      gcp_kms_encryption_key = var.kms_key
    }
  }

  backup_schedule {
    cron_schedule = var.cron
  }

  retention_policy {
    backup_retain_days = var.retain_days
  }
}

output "id" {
  value = google_gke_backup_backup_plan.this.id
}
