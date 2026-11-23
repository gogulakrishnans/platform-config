variable "repo_root" {
  type = string
}

variable "customer" {
  type = string
}

variable "side" {
  type = string
  validation {
    condition     = contains(["nonprod", "prod"], var.side)
    error_message = "side must be nonprod or prod."
  }
}
