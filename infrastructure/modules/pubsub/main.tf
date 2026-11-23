# One Pub/Sub topic per customer x product x environment, with optional push subscriptions to
# internal-only Cloud Run services (OIDC), each with its own dead-letter topic and retry policy
# (architecture §8). Message storage stays in the customer's region and DR pair.

variable "project_id" {
  type = string
}

variable "project_number" {
  description = "Data project number (Pub/Sub service agent)."
  type        = string
}

variable "name" {
  type = string
}

variable "regions" {
  description = "Allowed persistence regions (primary + DR pair)."
  type        = list(string)
}

variable "kms_key" {
  type = string
}

variable "publishers" {
  description = "Members allowed to publish."
  type        = list(string)
  default     = []
}

variable "subscriptions" {
  type = map(object({
    push_endpoint         = string
    oidc_service_account  = string
    audience              = optional(string)
    max_delivery_attempts = optional(number, 10)
    ack_deadline_seconds  = optional(number, 60)
  }))
  default = {}
}

variable "labels" {
  type = map(string)
}

variable "deletion_policy" {
  type    = string
  default = "DELETE"
}

locals {
  pubsub_agent = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic" "this" {
  project                    = var.project_id
  name                       = var.name
  labels                     = var.labels
  kms_key_name               = var.kms_key
  message_retention_duration = "604800s"
  deletion_policy            = var.deletion_policy

  message_storage_policy {
    allowed_persistence_regions = var.regions
  }
}

resource "google_pubsub_topic_iam_member" "publishers" {
  for_each = toset(var.publishers)

  project = var.project_id
  topic   = google_pubsub_topic.this.name
  role    = "roles/pubsub.publisher"
  member  = each.value
}

resource "google_pubsub_topic" "dlq" {
  for_each = var.subscriptions

  project         = var.project_id
  name            = "${each.key}-dlq"
  labels          = var.labels
  kms_key_name    = var.kms_key
  deletion_policy = var.deletion_policy

  message_storage_policy {
    allowed_persistence_regions = var.regions
  }
}

resource "google_pubsub_subscription" "this" {
  for_each = var.subscriptions

  project                    = var.project_id
  name                       = each.key
  topic                      = google_pubsub_topic.this.id
  labels                     = var.labels
  ack_deadline_seconds       = each.value.ack_deadline_seconds
  message_retention_duration = "604800s"
  deletion_policy            = var.deletion_policy

  push_config {
    push_endpoint = each.value.push_endpoint
    oidc_token {
      service_account_email = each.value.oidc_service_account
      audience              = coalesce(each.value.audience, each.value.push_endpoint)
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dlq[each.key].id
    max_delivery_attempts = each.value.max_delivery_attempts
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

# The Pub/Sub service agent forwards undeliverable messages and mints OIDC tokens for push.
resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  for_each = var.subscriptions

  project = var.project_id
  topic   = google_pubsub_topic.dlq[each.key].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent
}

resource "google_pubsub_subscription_iam_member" "dlq_subscriber" {
  for_each = var.subscriptions

  project      = var.project_id
  subscription = google_pubsub_subscription.this[each.key].name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}

output "topic_id" {
  value = google_pubsub_topic.this.id
}

output "subscriptions" {
  value = { for k, s in google_pubsub_subscription.this : k => s.id }
}
