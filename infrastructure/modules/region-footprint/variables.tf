variable "repo_root" {
  type = string
}

variable "region" {
  type = string
}

variable "group" {
  type = string
  validation {
    condition     = contains(["devstage", "uat", "prod"], var.group)
    error_message = "group must be devstage, uat or prod."
  }
}

variable "designate_dr_replica" {
  description = "false only for the first apply of a new prod cell (the replica must exist before it is designated)."
  type        = bool
  default     = true
}

variable "db_bootstrap_version" {
  type    = string
  default = "1.0.0"
}

variable "write_inventory" {
  description = "Write inventory/clusters|sql/*.yaml after apply (the pipeline commits them)."
  type        = bool
  default     = true
}
