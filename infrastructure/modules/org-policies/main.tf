# Organization policy guardrails on the Platform folder (architecture §2).

variable "parent" {
  description = "folders/NNN or organizations/NNN."
  type        = string
}

variable "allowed_locations" {
  description = "Values for gcp.resourceLocations, e.g. [\"in:us-east1-locations\", \"in:us-central1-locations\", \"us\"]."
  type        = list(string)
}

variable "trusted_image_projects" {
  description = "Projects allowed as image sources, e.g. [\"projects/pfx-platform-prod\"]."
  type        = list(string)
}

variable "org_id" {
  type = string
}

variable "cmek_required_services" {
  description = "Services that must use CMEK (gcp.restrictNonCmekServices)."
  type        = list(string)
  default     = ["storage.googleapis.com", "bigquery.googleapis.com", "pubsub.googleapis.com", "sqladmin.googleapis.com"]
}

locals {
  boolean_constraints = [
    "compute.requireOsLogin",
    "compute.requireShieldedVm",
    "compute.skipDefaultNetworkCreation",
    "compute.disableSerialPortAccess",
    "iam.disableServiceAccountKeyCreation",
    "iam.automaticIamGrantsForDefaultServiceAccounts",
    "storage.uniformBucketLevelAccess",
    "storage.publicAccessPrevention",
    "sql.restrictPublicIp",
  ]
  list_constraints = {
    "gcp.resourceLocations"        = { allowed = var.allowed_locations, denied = [] }
    "compute.trustedImageProjects" = { allowed = var.trusted_image_projects, denied = [] }
    "run.allowedIngress"           = { allowed = ["internal-and-cloud-load-balancing"], denied = [] }
    "gcp.restrictNonCmekServices"  = { allowed = [], denied = var.cmek_required_services }
    "compute.restrictVpcPeering"   = { allowed = ["under:organizations/${var.org_id}"], denied = [] }
  }
}

resource "google_org_policy_policy" "boolean" {
  for_each = toset(local.boolean_constraints)

  name   = "${var.parent}/policies/${each.value}"
  parent = var.parent

  spec {
    rules {
      enforce = "TRUE"
    }
  }
}

resource "google_org_policy_policy" "deny_external_ip" {
  name   = "${var.parent}/policies/compute.vmExternalIpAccess"
  parent = var.parent

  spec {
    rules {
      deny_all = "TRUE"
    }
  }
}

resource "google_org_policy_policy" "list" {
  for_each = local.list_constraints

  name   = "${var.parent}/policies/${each.key}"
  parent = var.parent

  spec {
    rules {
      values {
        allowed_values = length(each.value.allowed) > 0 ? each.value.allowed : null
        denied_values  = length(each.value.denied) > 0 ? each.value.denied : null
      }
    }
  }
}

output "policies" {
  value = concat(
    keys(google_org_policy_policy.boolean),
    keys(google_org_policy_policy.list),
    ["compute.vmExternalIpAccess"],
  )
}
