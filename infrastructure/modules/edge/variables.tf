variable "repo_root" {
  type = string
}

variable "group" {
  type = string
  validation {
    condition     = contains(["devstage", "uat", "prod"], var.group)
    error_message = "group must be devstage, uat or prod."
  }
}

variable "region" {
  description = "Region of the Dev/Stage internal ALB (devstage only)."
  type        = string
  default     = null
}
