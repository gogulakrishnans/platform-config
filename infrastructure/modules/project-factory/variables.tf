variable "project_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be 6-30 characters (kept <= 30 for Cloud SQL IAM user names, verification V1)."
  }
}

variable "display_name" {
  type = string
}

variable "folder_id" {
  description = "Parent folder, e.g. folders/123."
  type        = string
}

variable "billing_account" {
  type = string
}

variable "labels" {
  description = "Mandatory labels (modules/labels)."
  type        = map(string)
  validation {
    condition = alltrue([for k in ["customer", "environment", "env-group", "product", "region-role", "managed-by"] :
    contains(keys(var.labels), k)])
    error_message = "labels must contain the six mandatory keys."
  }
}

variable "services" {
  description = "APIs to enable."
  type        = list(string)
  default     = []
}

variable "shared_vpc_host" {
  type    = bool
  default = false
}

variable "shared_vpc_host_project" {
  description = "Host project ID when this project is a Shared VPC service project."
  type        = string
  default     = null
}

variable "budget" {
  type = object({
    amount     = number
    currency   = optional(string, "USD")
    thresholds = optional(list(number), [0.5, 0.8, 1.0])
  })
  default = { amount = 1000 }
}

variable "audit_log_destination" {
  description = "Central log bucket, e.g. logging.googleapis.com/projects/P/locations/global/buckets/B."
  type        = string
  default     = null
}

variable "quota_preferences" {
  description = "Quota preferences keyed by a stable name. Confirm quota_id with `gcloud beta quotas info list`."
  type = map(object({
    service         = string
    quota_id        = string
    preferred_value = number
    dimensions      = optional(map(string), {})
    justification   = optional(string, "Multi-tenant platform sizing (docs/gcp-verification.md)")
  }))
  default = {}
}

variable "quota_contact_email" {
  type    = string
  default = null
}

variable "deletion_policy" {
  type    = string
  default = "PREVENT"
  validation {
    condition     = contains(["PREVENT", "ABANDON", "DELETE"], var.deletion_policy)
    error_message = "deletion_policy must be PREVENT, ABANDON or DELETE."
  }
}
