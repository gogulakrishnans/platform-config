# Key ring in one or more locations with a set of keys and IAM (architecture §10).
# Key rings cannot be deleted in Cloud KMS; destroying keys schedules version destruction
# (crypto-shredding on offboarding).

variable "project_id" {
  type = string
}

variable "name" {
  description = "Key ring name, e.g. kr-acme-corp-prod."
  type        = string
}

variable "locations" {
  type = list(string)
}

variable "keys" {
  description = "Key names created in every location."
  type        = list(string)
}

variable "rotation_period" {
  type    = string
  default = "7776000s" # 90 days
}

variable "iam" {
  description = "Grants applied to every location's copy of a key."
  type = list(object({
    key    = string
    role   = string
    member = string
  }))
  default = []
}

variable "labels" {
  type = map(string)
}

variable "deletion_policy" {
  type    = string
  default = "PREVENT"
}

locals {
  keys = { for pair in setproduct(var.locations, var.keys) : "${pair[0]}/${pair[1]}" => { location = pair[0], key = pair[1] } }
  grants = {
    for g in flatten([for loc in var.locations : [for b in var.iam : merge(b, { location = loc })]]) :
    "${g.location}/${g.key}/${g.role}/${g.member}" => g
  }
}

resource "google_kms_key_ring" "this" {
  for_each = toset(var.locations)

  project  = var.project_id
  name     = var.name
  location = each.value
}

resource "google_kms_crypto_key" "this" {
  for_each = local.keys

  name            = each.value.key
  key_ring        = google_kms_key_ring.this[each.value.location].id
  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = var.rotation_period
  labels          = var.labels
  deletion_policy = var.deletion_policy
}

resource "google_kms_crypto_key_iam_member" "this" {
  for_each = local.grants

  crypto_key_id = google_kms_crypto_key.this["${each.value.location}/${each.value.key}"].id
  role          = each.value.role
  member        = each.value.member
}

output "key_ids" {
  description = "location/key => key ID."
  value       = { for k, v in google_kms_crypto_key.this : k => v.id }
}
