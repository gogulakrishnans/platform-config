# One BigQuery dataset with dataset IAM and a customer key. Prod datasets get a DR dataset in the
# pair region, pre-created with a CMEK key there, filled by a daily cross-region copy
# (BigQuery Data Transfer Service, RPO 24 h, verification V4).

variable "project_id" {
  type = string
}

variable "dataset_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9_]*$", var.dataset_id)) && length(var.dataset_id) <= 1024
    error_message = "dataset_id: lowercase letters, digits and underscores."
  }
}

variable "location" {
  type = string
}

variable "kms_key" {
  type = string
}

variable "iam" {
  type = list(object({
    role   = string
    member = string
  }))
  default = []
}

variable "dr" {
  type = object({
    location       = string
    kms_key        = string
    transfer_agent = string # service account that runs the copy
  })
  default = null
}

variable "labels" {
  type = map(string)
}

variable "deletion_policy" {
  type    = string
  default = "PREVENT"
}

resource "google_bigquery_dataset" "this" {
  project                    = var.project_id
  dataset_id                 = var.dataset_id
  location                   = var.location
  labels                     = var.labels
  delete_contents_on_destroy = false
  deletion_policy            = var.deletion_policy

  default_encryption_configuration {
    kms_key_name = var.kms_key
  }
}

resource "google_bigquery_dataset_iam_member" "this" {
  for_each = { for b in var.iam : "${b.role}/${b.member}" => b }

  project    = var.project_id
  dataset_id = google_bigquery_dataset.this.dataset_id
  role       = each.value.role
  member     = each.value.member
}

resource "google_bigquery_dataset" "dr" {
  count = var.dr == null ? 0 : 1

  project                    = var.project_id
  dataset_id                 = "${var.dataset_id}_dr"
  location                   = var.dr.location
  labels                     = merge(var.labels, { "region-role" = "dr" })
  delete_contents_on_destroy = false
  deletion_policy            = var.deletion_policy

  default_encryption_configuration {
    kms_key_name = var.dr.kms_key
  }
}

resource "google_bigquery_data_transfer_config" "dr_copy" {
  count = var.dr == null ? 0 : 1

  project                = var.project_id
  display_name           = "dr-copy-${var.dataset_id}"
  location               = var.dr.location
  data_source_id         = "cross_region_copy"
  schedule               = "every 24 hours"
  destination_dataset_id = google_bigquery_dataset.dr[0].dataset_id
  service_account_name   = var.dr.transfer_agent

  params = {
    source_dataset_id           = google_bigquery_dataset.this.dataset_id
    source_project_id           = var.project_id
    overwrite_destination_table = "true"
  }
}

output "dataset_id" {
  value = google_bigquery_dataset.this.dataset_id
}

output "dr_dataset_id" {
  value = try(google_bigquery_dataset.dr[0].dataset_id, null)
}
