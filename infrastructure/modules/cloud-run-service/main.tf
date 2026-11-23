# Cloud Run service per customer x product x environment (architecture §5). Terraform owns the
# shape; the L4 deploy step owns the image and traffic split (ignore_changes, clarification C11).

variable "project_id" {
  type = string
}

variable "name" {
  description = "{customer}-{product}-{env}"
  type        = string
  validation {
    condition     = length(var.name) <= 49
    error_message = "Cloud Run service names are limited to 49 characters."
  }
}

variable "region" {
  type = string
}

variable "service_account" {
  description = "Customer environment GSA."
  type        = string
}

variable "image" {
  description = "Initial image (placeholder). The deploy step manages revisions afterwards."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/placeholder:latest"
}

variable "port" {
  type    = number
  default = 8080
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type    = number
  default = 10
}

variable "network" {
  type = string
}

variable "subnetwork" {
  type = string
}

variable "network_tags" {
  type    = list(string)
  default = []
}

variable "env" {
  type    = map(string)
  default = {}
}

variable "public_via_lb" {
  description = "Reached through the external/internal ALB with JWT checked in the app (invoker IAM check disabled; ingress still internal-and-cloud-load-balancing)."
  type        = bool
  default     = true
}

variable "invokers" {
  description = "Members granted roles/run.invoker (e.g. the push subscription identity)."
  type        = list(string)
  default     = []
}

variable "migration_job" {
  description = "Create the {name}-migrate Cloud Run job (primary region only)."
  type        = bool
  default     = true
}

variable "labels" {
  type = map(string)
}

variable "deletion_policy" {
  type    = string
  default = "DELETE"
}

locals {
  vpc_access = {
    network    = var.network
    subnetwork = var.subnetwork
    tags       = concat(["run"], var.network_tags)
  }
}

resource "google_cloud_run_v2_service" "this" {
  project              = var.project_id
  name                 = var.name
  location             = var.region
  labels               = var.labels
  ingress              = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  invoker_iam_disabled = var.public_via_lb
  deletion_protection  = var.deletion_policy == "PREVENT"
  deletion_policy      = var.deletion_policy

  binary_authorization {
    use_default = true
  }

  template {
    service_account                  = var.service_account
    labels                           = var.labels
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = local.vpc_access.network
        subnetwork = local.vpc_access.subnetwork
        tags       = local.vpc_access.tags
      }
    }

    containers {
      image = var.image

      ports {
        container_port = var.port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      startup_probe {
        http_get {
          path = "/healthz/ready"
        }
      }

      liveness_probe {
        http_get {
          path = "/healthz/live"
        }
      }

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      traffic,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = toset(var.invokers)

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = each.value
}

resource "google_cloud_run_v2_job" "migrate" {
  count = var.migration_job ? 1 : 0

  project             = var.project_id
  name                = "${var.name}-migrate"
  location            = var.region
  labels              = var.labels
  deletion_protection = false

  binary_authorization {
    use_default = true
  }

  template {
    labels = var.labels
    template {
      service_account = var.service_account
      max_retries     = 1
      timeout         = "1800s"

      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = local.vpc_access.network
          subnetwork = local.vpc_access.subnetwork
          tags       = local.vpc_access.tags
        }
      }

      containers {
        image = var.image
        args  = ["migrate"]
        dynamic "env" {
          for_each = var.env
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
}

resource "google_compute_region_network_endpoint_group" "neg" {
  project               = var.project_id
  name                  = "neg-${var.name}"
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.this.name
  }
}

output "name" {
  value = google_cloud_run_v2_service.this.name
}

output "uri" {
  value = google_cloud_run_v2_service.this.uri
}

output "neg_id" {
  value = google_compute_region_network_endpoint_group.neg.id
}
