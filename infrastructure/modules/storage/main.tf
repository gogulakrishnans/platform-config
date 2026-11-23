# One GCS bucket with bucket-level IAM and a customer key (architecture §8). Prod buckets are
# configurable dual-region (primary + DR pair) with turbo replication; the key lives in the matching
# multi-region (verification V5).

variable "project_id" {
  type = string
}

variable "name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.name))
    error_message = "bucket names are 3-63 characters, lowercase, digits and hyphens."
  }
}

variable "location" {
  description = "Region (non-prod) or multi-region code for a dual-region bucket (e.g. US)."
  type        = string
}

variable "dual_region" {
  description = "[primary, pair] for a configurable dual-region bucket with turbo replication."
  type        = list(string)
  default     = []
}

variable "kms_key" {
  type = string
}

variable "versioning" {
  type    = bool
  default = true
}

variable "soft_delete_days" {
  type    = number
  default = 7
}

variable "delete_after_days" {
  description = "Lifecycle: delete objects older than N days (0 = keep)."
  type        = number
  default     = 0
}

variable "iam" {
  type = list(object({
    role   = string
    member = string
  }))
  default = []
}

variable "labels" {
  type = map(string)
}

variable "deletion_policy" {
  type    = string
  default = "PREVENT"
}

resource "google_storage_bucket" "this" {
  project                     = var.project_id
  name                        = var.name
  location                    = upper(var.location)
  storage_class               = "STANDARD"
  labels                      = var.labels
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  rpo                         = length(var.dual_region) == 2 ? "ASYNC_TURBO" : null
  deletion_policy             = var.deletion_policy

  dynamic "custom_placement_config" {
    for_each = length(var.dual_region) == 2 ? [var.dual_region] : []
    content {
      data_locations = [for r in custom_placement_config.value : upper(r)]
    }
  }

  versioning {
    enabled = var.versioning
  }

  soft_delete_policy {
    retention_duration_seconds = var.soft_delete_days * 86400
  }

  encryption {
    default_kms_key_name = var.kms_key
  }

  dynamic "lifecycle_rule" {
    for_each = var.delete_after_days > 0 ? [var.delete_after_days] : []
    content {
      condition {
        age = lifecycle_rule.value
      }
      action {
        type = "Delete"
      }
    }
  }
}

resource "google_storage_bucket_iam_member" "this" {
  for_each = { for b in var.iam : "${b.role}/${b.member}" => b }

  bucket = google_storage_bucket.this.name
  role   = each.value.role
  member = each.value.member
}

output "name" {
  value = google_storage_bucket.this.name
}

output "url" {
  value = google_storage_bucket.this.url
}
