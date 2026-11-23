# Mandatory labels (architecture §16). Every module builds its labels through this module so the
# six keys are always present and valid. No resources.

variable "customer" {
  description = "Owner customer ID, or \"shared\" for platform resources."
  type        = string
  default     = "shared"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.customer)) || var.customer == "shared"
    error_message = "customer must be a valid customer ID (3-20 chars, [a-z0-9-]) or \"shared\"."
  }
}

variable "environment" {
  type    = string
  default = "shared"
  validation {
    condition     = contains(["dev", "stage", "uat", "prod", "shared"], var.environment)
    error_message = "environment must be dev, stage, uat, prod or shared."
  }
}

variable "env_group" {
  type    = string
  default = "shared"
  validation {
    condition     = contains(["devstage", "uat", "prod", "shared"], var.env_group)
    error_message = "env_group must be devstage, uat, prod or shared."
  }
}

variable "product" {
  description = "Product short code, or \"platform\" for shared resources."
  type        = string
  default     = "platform"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,11}$", var.product))
    error_message = "product must be a short code of up to 12 characters."
  }
}

variable "region_role" {
  type    = string
  default = "primary"
  validation {
    condition     = contains(["primary", "dr"], var.region_role)
    error_message = "region_role must be primary or dr."
  }
}

variable "managed_by" {
  type    = string
  default = "terraform"
  validation {
    condition     = contains(["terraform", "argocd"], var.managed_by)
    error_message = "managed_by must be terraform or argocd."
  }
}

variable "extra" {
  description = "Additional labels. Cannot override the mandatory keys."
  type        = map(string)
  default     = {}
}

locals {
  mandatory = {
    customer      = var.customer
    environment   = var.environment
    "env-group"   = var.env_group
    product       = var.product
    "region-role" = var.region_role
    "managed-by"  = var.managed_by
  }
}

output "labels" {
  description = "Label map with the six mandatory keys."
  value       = merge(var.extra, local.mandatory)
}

output "mandatory_keys" {
  value = keys(local.mandatory)
}
