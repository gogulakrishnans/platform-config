variable "repo_root" {
  description = "Path to the repository root."
  type        = string
}

variable "customer" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.customer))
    error_message = "customer must be a valid customer ID (3-20 chars)."
  }
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "stage", "uat", "prod"], var.environment)
    error_message = "environment must be dev, stage, uat or prod."
  }
}
