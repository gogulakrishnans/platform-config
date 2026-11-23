variable "project_id" {
  description = "Shared VPC host project."
  type        = string
}

variable "name" {
  description = "VPC name, e.g. vpc-prod."
  type        = string
}

variable "psa_ranges" {
  description = "Region => CIDR for private services access (registry ip_plan.<region>.<side>.psa)."
  type        = map(string)
  default     = {}
}

variable "private_zone" {
  description = "Private DNS zone, e.g. platform.internal (non-prod)."
  type        = string
  default     = null
}

variable "public_zones" {
  description = "Public DNS zones, e.g. [\"platform.example\", \"uat.platform.example\"]."
  type        = list(string)
  default     = []
}

variable "labels" {
  type = map(string)
}
