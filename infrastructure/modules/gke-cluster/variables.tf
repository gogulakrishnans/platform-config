variable "project_id" {
  description = "Compute (or platform) service project."
  type        = string
}

variable "project_number" {
  type = string
}

variable "host_project_id" {
  description = "Shared VPC host project."
  type        = string
}

variable "network_id" {
  type = string
}

variable "name" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,38}[a-z0-9]$", var.name))
    error_message = "cluster name must be <= 40 characters."
  }
}

variable "region" {
  type = string
}

variable "zones" {
  type = list(string)
  validation {
    condition     = length(var.zones) == 3
    error_message = "clusters run node pools across three zones."
  }
}

variable "cluster_type" {
  description = "regional (UAT, Prod, management) or zonal (Dev/Stage: zonal control plane, nodes in 3 zones)."
  type        = string
  default     = "regional"
  validation {
    condition     = contains(["regional", "zonal"], var.cluster_type)
    error_message = "cluster_type must be regional or zonal."
  }
}

variable "ranges" {
  description = "registry cluster_plan ranges."
  type = object({
    nodes    = string
    pods     = string
    services = string
  })
}

variable "release_channel" {
  type = string
  validation {
    condition     = contains(["RAPID", "REGULAR", "STABLE"], var.release_channel)
    error_message = "release_channel must be RAPID, REGULAR or STABLE."
  }
}

variable "node_service_account" {
  type = string
}

variable "node_pools" {
  type = map(object({
    machine_type = string
    min_nodes    = number
    max_nodes    = number
    taints = optional(list(object({
      key    = string
      value  = string
      effect = string
    })), [])
  }))
}

variable "max_pods_per_node" {
  type    = number
  default = 64
}

variable "secrets_encryption_key" {
  description = "Cloud KMS key for application-layer secrets encryption (platform key)."
  type        = string
  default     = null
}

variable "maintenance_recurrence" {
  type    = string
  default = "FREQ=WEEKLY;BYDAY=SA,SU"
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "labels" {
  type = map(string)
}
