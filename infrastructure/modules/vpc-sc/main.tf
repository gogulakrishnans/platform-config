# VPC Service Controls perimeters (architecture §2). While runners are not yet live, the perimeters
# are created in dry-run (spec) mode; set enforce = true to move the same config to status.

variable "access_policy" {
  description = "Access policy number."
  type        = string
}

variable "enforce" {
  description = "false = dry-run spec only; true = enforced status."
  type        = bool
  default     = false
}

variable "restricted_services" {
  type = list(string)
  default = [
    "artifactregistry.googleapis.com", "bigquery.googleapis.com", "cloudkms.googleapis.com",
    "compute.googleapis.com", "container.googleapis.com", "dns.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com", "pubsub.googleapis.com",
    "run.googleapis.com", "secretmanager.googleapis.com", "sqladmin.googleapis.com",
    "storage.googleapis.com", "storagetransfer.googleapis.com", "bigquerydatatransfer.googleapis.com",
    "gkebackup.googleapis.com", "binaryauthorization.googleapis.com", "certificatemanager.googleapis.com",
    "cloudfunctions.googleapis.com", "iam.googleapis.com",
  ]
}

variable "perimeters" {
  description = "Perimeter name => member project numbers plus ingress/egress rules."
  type = map(object({
    project_numbers = list(string)
    ingress = optional(list(object({
      title         = string
      identities    = optional(list(string), [])
      identity_type = optional(string)  # e.g. ANY_SERVICE_ACCOUNT
      sources       = list(string)      # "projects/NUM" or access levels
      resources     = list(string)      # "projects/NUM" or ["*"]
      services      = map(list(string)) # service => methods ("*" = all)
    })), [])
    egress = optional(list(object({
      title         = string
      identities    = optional(list(string), [])
      identity_type = optional(string)
      resources     = list(string)
      services      = map(list(string))
    })), [])
  }))
}

locals {
  perimeter_config = {
    for name, p in var.perimeters : name => {
      resources = [for n in p.project_numbers : "projects/${n}"]
      ingress   = p.ingress
      egress    = p.egress
    }
  }
}

resource "google_access_context_manager_service_perimeter" "this" {
  for_each = local.perimeter_config

  parent                    = "accessPolicies/${var.access_policy}"
  name                      = "accessPolicies/${var.access_policy}/servicePerimeters/${replace(each.key, "-", "_")}"
  title                     = each.key
  perimeter_type            = "PERIMETER_TYPE_REGULAR"
  use_explicit_dry_run_spec = !var.enforce

  dynamic "status" {
    for_each = var.enforce ? [each.value] : []
    content {
      resources           = status.value.resources
      restricted_services = var.restricted_services

      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = ["RESTRICTED-SERVICES"]
      }

      dynamic "ingress_policies" {
        for_each = status.value.ingress
        content {
          title = ingress_policies.value.title
          ingress_from {
            identities    = length(ingress_policies.value.identities) > 0 ? ingress_policies.value.identities : null
            identity_type = ingress_policies.value.identity_type
            dynamic "sources" {
              for_each = ingress_policies.value.sources
              content {
                resource = sources.value
              }
            }
          }
          ingress_to {
            resources = ingress_policies.value.resources
            dynamic "operations" {
              for_each = ingress_policies.value.services
              content {
                service_name = operations.key
                dynamic "method_selectors" {
                  for_each = operations.value
                  content {
                    method = method_selectors.value
                  }
                }
              }
            }
          }
        }
      }

      dynamic "egress_policies" {
        for_each = status.value.egress
        content {
          title = egress_policies.value.title
          egress_from {
            identities    = length(egress_policies.value.identities) > 0 ? egress_policies.value.identities : null
            identity_type = egress_policies.value.identity_type
          }
          egress_to {
            resources = egress_policies.value.resources
            dynamic "operations" {
              for_each = egress_policies.value.services
              content {
                service_name = operations.key
                dynamic "method_selectors" {
                  for_each = operations.value
                  content {
                    method = method_selectors.value
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  dynamic "spec" {
    for_each = var.enforce ? [] : [each.value]
    content {
      resources           = spec.value.resources
      restricted_services = var.restricted_services

      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = ["RESTRICTED-SERVICES"]
      }

      dynamic "ingress_policies" {
        for_each = spec.value.ingress
        content {
          title = ingress_policies.value.title
          ingress_from {
            identities    = length(ingress_policies.value.identities) > 0 ? ingress_policies.value.identities : null
            identity_type = ingress_policies.value.identity_type
            dynamic "sources" {
              for_each = ingress_policies.value.sources
              content {
                resource = sources.value
              }
            }
          }
          ingress_to {
            resources = ingress_policies.value.resources
            dynamic "operations" {
              for_each = ingress_policies.value.services
              content {
                service_name = operations.key
                dynamic "method_selectors" {
                  for_each = operations.value
                  content {
                    method = method_selectors.value
                  }
                }
              }
            }
          }
        }
      }

      dynamic "egress_policies" {
        for_each = spec.value.egress
        content {
          title = egress_policies.value.title
          egress_from {
            identities    = length(egress_policies.value.identities) > 0 ? egress_policies.value.identities : null
            identity_type = egress_policies.value.identity_type
          }
          egress_to {
            resources = egress_policies.value.resources
            dynamic "operations" {
              for_each = egress_policies.value.services
              content {
                service_name = operations.key
                dynamic "method_selectors" {
                  for_each = operations.value
                  content {
                    method = method_selectors.value
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

output "perimeters" {
  value = { for k, p in google_access_context_manager_service_perimeter.this : k => p.name }
}
