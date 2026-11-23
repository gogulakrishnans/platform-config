variable "repo_root" {
  type = string
}

variable "side" {
  type = string
  validation {
    condition     = contains(["nonprod", "prod"], var.side)
    error_message = "side must be nonprod or prod."
  }
}

variable "terraform_service_account" {
  description = "L0 Terraform service account of this side (tf-nonprod@ / tf-prod@ in the seed project)."
  type        = string
}

variable "ansible_image" {
  description = "Hardened image for Ansible runners (trusted image project)."
  type        = string
}

variable "ansible_runners" {
  type    = number
  default = 1
}
