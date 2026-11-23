variable "project_id" {
  type = string
}

variable "name" {
  description = "LB name suffix, e.g. prod-edge, devstage-us-east1."
  type        = string
}

variable "scheme" {
  type = string
  validation {
    condition     = contains(["EXTERNAL_MANAGED", "INTERNAL_MANAGED"], var.scheme)
    error_message = "scheme must be EXTERNAL_MANAGED (global) or INTERNAL_MANAGED (regional)."
  }
}

variable "region" {
  description = "Region of a regional internal ALB."
  type        = string
  default     = null
}

variable "network" {
  type    = string
  default = null
}

variable "subnetwork" {
  description = "Subnet for the internal ALB VIP."
  type        = string
  default     = null
}

variable "backends" {
  type = map(object({
    kind       = string # neg | serverless | mig
    enable_cdn = optional(bool, false)
    groups = list(object({
      group           = string
      capacity_scaler = optional(number, 1)
    }))
    health_check = optional(object({
      protocol = string
      port     = number
      path     = string
    }))
  }))
  validation {
    condition     = alltrue([for b in values(var.backends) : contains(["neg", "serverless", "mig"], b.kind)])
    error_message = "backend kind must be neg, serverless or mig."
  }
  validation {
    condition     = alltrue([for b in values(var.backends) : b.kind == "serverless" || b.health_check != null])
    error_message = "neg and mig backends need a health_check."
  }
}

variable "host_rules" {
  description = "Path matcher name => hosts, default backend key and path rules."
  type = map(object({
    hosts           = list(string)
    default_backend = string
    paths = optional(list(object({
      paths   = list(string)
      backend = string
    })), [])
  }))
}

variable "default_redirect_host" {
  description = "Unknown hosts are redirected here."
  type        = string
}

variable "certificate_map" {
  description = "Certificate Manager map ID (global external)."
  type        = string
  default     = null
}

variable "certificates" {
  description = "Regional Certificate Manager certificate IDs (internal)."
  type        = list(string)
  default     = []
}

variable "security_policy" {
  description = "Cloud Armor policy ID (global external)."
  type        = string
  default     = null
}

variable "iap" {
  description = "Enable IAP on backend services (internal operator access)."
  type        = bool
  default     = false
}

variable "labels" {
  type = map(string)
}
