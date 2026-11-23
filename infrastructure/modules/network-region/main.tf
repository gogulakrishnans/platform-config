# Regional footprint of one side's Shared VPC (L2): shared subnets, Cloud Router and Cloud NAT.
# Per-cluster node subnets are created by modules/gke-cluster (decisions #23).

variable "project_id" {
  description = "Shared VPC host project."
  type        = string
}

variable "network_id" {
  type = string
}

variable "network_name" {
  type = string
}

variable "region" {
  type = string
}

variable "side" {
  type = string
  validation {
    condition     = contains(["nonprod", "prod"], var.side)
    error_message = "side must be nonprod or prod."
  }
}

variable "ranges" {
  description = "registry ip_plan.<region>.<side>: run, mig, proxy, ops."
  type = object({
    run   = string
    mig   = string
    proxy = string
    ops   = string
  })
}

variable "nat_static_ips" {
  description = "Number of static NAT IPs (prod publishes them for customer allowlists). 0 = auto-allocated."
  type        = number
  default     = 0
}

variable "labels" {
  type = map(string)
}

variable "service_project_numbers" {
  description = "Project numbers of service projects that deploy into the shared subnets (Cloud Run, MIGs)."
  type        = map(string)
  default     = {}
}

locals {
  subnets = {
    run = { cidr = var.ranges.run, purpose = null }
    mig = { cidr = var.ranges.mig, purpose = null }
    ops = { cidr = var.ranges.ops, purpose = null }
  }
}

resource "google_compute_subnetwork" "this" {
  for_each = local.subnets

  project                  = var.project_id
  name                     = "snet-${each.key}-${var.region}"
  region                   = var.region
  network                  = var.network_id
  ip_cidr_range            = each.value.cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_subnetwork" "proxy_only" {
  project       = var.project_id
  name          = "snet-proxy-${var.region}"
  region        = var.region
  network       = var.network_id
  ip_cidr_range = var.ranges.proxy
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
}

resource "google_compute_firewall" "allow_proxy_only" {
  project   = var.project_id
  name      = "${var.network_name}-allow-proxy-${var.region}"
  network   = var.network_id
  direction = "INGRESS"
  priority  = 1000

  allow {
    protocol = "tcp"
    ports    = ["443", "8080", "8443", "15021"]
  }
  source_ranges = [var.ranges.proxy]
  target_tags   = ["lb-backend"]
}

# Cloud Run and MIG service accounts in compute projects may use the run/mig subnets.
resource "google_compute_subnetwork_iam_member" "users" {
  for_each = {
    for pair in setproduct(keys(var.service_project_numbers), ["run", "mig"]) :
    "${pair[0]}/${pair[1]}" => { number = var.service_project_numbers[pair[0]], subnet = pair[1] }
  }

  project    = var.project_id
  region     = var.region
  subnetwork = google_compute_subnetwork.this[each.value.subnet].name
  role       = "roles/compute.networkUser"
  member     = "serviceAccount:${each.value.number}@cloudservices.gserviceaccount.com"
}

resource "google_compute_subnetwork_iam_member" "run_agents" {
  for_each = var.service_project_numbers

  project    = var.project_id
  region     = var.region
  subnetwork = google_compute_subnetwork.this["run"].name
  role       = "roles/compute.networkUser"
  member     = "serviceAccount:service-${each.value}@serverless-robot-prod.iam.gserviceaccount.com"
}

resource "google_compute_router" "this" {
  project     = var.project_id
  name        = "cr-${var.region}"
  region      = var.region
  network     = var.network_id
  description = "Cloud Router for vpc-${var.side} in ${var.region}"
}

resource "google_compute_address" "nat" {
  count = var.nat_static_ips

  project = var.project_id
  name    = "nat-${var.region}-${count.index}"
  region  = var.region
  labels  = var.labels
}

resource "google_compute_router_nat" "this" {
  project                            = var.project_id
  name                               = "nat-${var.region}"
  router                             = google_compute_router.this.name
  region                             = var.region
  nat_ip_allocate_option             = var.nat_static_ips > 0 ? "MANUAL_ONLY" : "AUTO_ONLY"
  nat_ips                            = google_compute_address.nat[*].self_link
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  enable_dynamic_port_allocation     = true
  min_ports_per_vm                   = 64
  max_ports_per_vm                   = 4096

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

output "subnets" {
  description = "run, mig, ops => self link."
  value       = { for k, s in google_compute_subnetwork.this : k => s.self_link }
}

output "proxy_subnet" {
  value = google_compute_subnetwork.proxy_only.self_link
}

output "nat_ips" {
  value = google_compute_address.nat[*].address
}
