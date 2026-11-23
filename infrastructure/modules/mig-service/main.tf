# Stateless regional MIG per customer x product x environment (architecture §5, §6). Shielded VM,
# no external IP, no data disks, customer environment GSA, per-tenant network tag. Terraform owns the
# shape; the L4 deploy step rolls new instance templates (ignore_changes on version, C11).

variable "project_id" {
  type = string
}

variable "name" {
  description = "{customer}-{product}-{env}"
  type        = string
}

variable "region" {
  type = string
}

variable "zones" {
  type = list(string)
}

variable "service_account" {
  type = string
}

variable "machine_type" {
  type = string
}

variable "source_image" {
  description = "Initial image (family URL in the trusted image project)."
  type        = string
}

variable "subnetwork" {
  type = string
}

variable "network_tags" {
  description = "Per-tenant tags, e.g. t-acme-corp-prod."
  type        = list(string)
}

variable "port" {
  type    = number
  default = 8443
}

variable "health_check_path" {
  type    = string
  default = "/healthz/ready"
}

variable "min_replicas" {
  type = number
}

variable "max_replicas" {
  type = number
}

variable "metadata" {
  type    = map(string)
  default = {}
}

variable "labels" {
  type = map(string)
}

resource "google_compute_health_check" "this" {
  project             = var.project_id
  name                = "hc-${var.name}"
  check_interval_sec  = 10
  timeout_sec         = 5
  healthy_threshold   = 2
  unhealthy_threshold = 3

  https_health_check {
    port         = var.port
    request_path = var.health_check_path
  }
}

resource "google_compute_region_instance_template" "this" {
  project      = var.project_id
  name_prefix  = "${var.name}-"
  region       = var.region
  machine_type = var.machine_type
  labels       = var.labels
  tags         = distinct(concat(["mig", "lb-backend"], var.network_tags))

  metadata = merge({
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
  }, var.metadata)

  disk {
    source_image = var.source_image
    boot         = true
    auto_delete  = true
    disk_type    = "pd-balanced"
    disk_size_gb = 20
    labels       = var.labels
  }

  network_interface {
    subnetwork = var.subnetwork
    # No access_config block: no external IP (org policy compute.vmExternalIpAccess).
  }

  service_account {
    email  = var.service_account
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_region_instance_group_manager" "this" {
  project                   = var.project_id
  name                      = var.name
  region                    = var.region
  base_instance_name        = var.name
  distribution_policy_zones = var.zones

  version {
    name              = "primary"
    instance_template = google_compute_region_instance_template.this.self_link
  }

  named_port {
    name = "https"
    port = var.port
  }

  auto_healing_policies {
    health_check      = google_compute_health_check.this.id
    initial_delay_sec = 300
  }

  update_policy {
    type                  = "PROACTIVE"
    minimal_action        = "REPLACE"
    max_surge_fixed       = length(var.zones) # at least one zone's worth
    max_unavailable_fixed = 0
    replacement_method    = "SUBSTITUTE"
  }

  lifecycle {
    ignore_changes = [version, target_size]
  }
}

resource "google_compute_region_autoscaler" "this" {
  project = var.project_id
  name    = "as-${var.name}"
  region  = var.region
  target  = google_compute_region_instance_group_manager.this.id

  autoscaling_policy {
    min_replicas    = var.min_replicas
    max_replicas    = var.max_replicas
    cooldown_period = 120

    cpu_utilization {
      target = 0.6
    }
  }
}

output "instance_group" {
  value = google_compute_region_instance_group_manager.this.instance_group
}

output "health_check" {
  value = google_compute_health_check.this.id
}
