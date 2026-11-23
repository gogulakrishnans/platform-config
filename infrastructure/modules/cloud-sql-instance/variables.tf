variable "project_id" {
  description = "Data project (data-nonprod or data-prod)."
  type        = string
}

variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "database_version" {
  type    = string
  default = "POSTGRES_16"
}

variable "tier" {
  type = string
}

variable "edition" {
  type    = string
  default = "ENTERPRISE"
  validation {
    condition     = contains(["ENTERPRISE", "ENTERPRISE_PLUS"], var.edition)
    error_message = "edition must be ENTERPRISE or ENTERPRISE_PLUS."
  }
}

variable "network_id" {
  description = "Shared VPC network (private services access)."
  type        = string
}

variable "psa_range_name" {
  type = string
}

variable "encryption_key" {
  description = "Platform CMEK key in the instance region (per-instance key, decisions #6)."
  type        = string
}

variable "dr" {
  description = "Cross-region DR replica (prod only)."
  type = object({
    region         = string
    encryption_key = string
    psa_range_name = string
  })
  default = null
}

variable "designate_dr_replica" {
  description = "Designate the replica for advanced DR. Set false only for the very first apply of a new instance."
  type        = bool
  default     = true
}

variable "bootstrap_service_account" {
  description = "Email of the database bootstrap job's service account (IAM user with cloudsqlsuperuser)."
  type        = string
  default     = null
}

variable "maintenance_track" {
  type    = string
  default = "stable"
}

variable "extra_flags" {
  type    = map(string)
  default = {}
}

variable "labels" {
  type = map(string)
}

variable "deletion_policy" {
  type    = string
  default = "PREVENT"
}
