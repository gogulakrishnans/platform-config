# One global Shared VPC per side (architecture §11): VPC, private services access for Cloud SQL
# (all active regions, verification V9), baseline firewall, and DNS for restricted Google APIs.
# Regional subnets, routers and NAT come from modules/network-region (L2).

resource "google_compute_network" "this" {
  project                 = var.project_id
  name                    = var.name
  auto_create_subnetworks = false
  routing_mode            = "GLOBAL"
}

# ---------------------------------------------------------------- private services access (Cloud SQL)

resource "google_compute_global_address" "psa" {
  for_each = var.psa_ranges

  project       = var.project_id
  name          = "psa-${each.key}"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = split("/", each.value)[0]
  prefix_length = tonumber(split("/", each.value)[1])
  network       = google_compute_network.this.id
  labels        = var.labels
}

resource "google_service_networking_connection" "psa" {
  count = length(var.psa_ranges) > 0 ? 1 : 0

  network                 = google_compute_network.this.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [for a in google_compute_global_address.psa : a.name]
}

# ---------------------------------------------------------------- baseline firewall

resource "google_compute_firewall" "deny_all_ingress" {
  project   = var.project_id
  name      = "${var.name}-deny-all-ingress"
  network   = google_compute_network.this.id
  direction = "INGRESS"
  priority  = 65000

  deny {
    protocol = "all"
  }
  source_ranges = ["0.0.0.0/0"]

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_firewall" "allow_lb_health_checks" {
  project   = var.project_id
  name      = "${var.name}-allow-lb-health-checks"
  network   = google_compute_network.this.id
  direction = "INGRESS"
  priority  = 1000

  allow {
    protocol = "tcp"
    ports    = ["443", "8080", "8443", "15021"]
  }
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"] # Google Front Ends and health checkers
  target_tags   = ["lb-backend"]
}

resource "google_compute_firewall" "allow_iap_ssh" {
  project   = var.project_id
  name      = "${var.name}-allow-iap-ssh"
  network   = google_compute_network.this.id
  direction = "INGRESS"
  priority  = 1000

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = ["35.235.240.0/20"] # IAP TCP forwarding
  target_tags   = ["ops"]
}

resource "google_compute_firewall" "allow_ansible_ssh" {
  project   = var.project_id
  name      = "${var.name}-allow-ansible-ssh"
  network   = google_compute_network.this.id
  direction = "INGRESS"
  priority  = 1000

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_tags = ["ansible-runner"]
  target_tags = ["mig"]
}

# Default-deny egress for MIGs and Cloud Run (tags), with explicit allows (architecture §11).
resource "google_compute_firewall" "deny_tenant_egress" {
  project   = var.project_id
  name      = "${var.name}-deny-tenant-egress"
  network   = google_compute_network.this.id
  direction = "EGRESS"
  priority  = 65000

  deny {
    protocol = "all"
  }
  destination_ranges = ["0.0.0.0/0"]
  target_tags        = ["mig", "run"]
}

resource "google_compute_firewall" "allow_tenant_egress_google_and_sql" {
  project   = var.project_id
  name      = "${var.name}-allow-tenant-egress-private"
  network   = google_compute_network.this.id
  direction = "EGRESS"
  priority  = 1000

  allow {
    protocol = "tcp"
    ports    = ["443", "3307", "5432"]
  }
  destination_ranges = concat(["199.36.153.4/30"], values(var.psa_ranges)) # restricted.googleapis.com + Cloud SQL
  target_tags        = ["mig", "run"]
}

resource "google_compute_firewall" "allow_tenant_egress_internet" {
  project   = var.project_id
  name      = "${var.name}-allow-egress-internet-443"
  network   = google_compute_network.this.id
  direction = "EGRESS"
  priority  = 1100

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
  destination_ranges = ["0.0.0.0/0"]
  target_tags        = ["egress-internet"] # added only for products whose catalog entry declares egress
}

# ---------------------------------------------------------------- DNS

# Route Google APIs to restricted.googleapis.com so traffic stays inside VPC-SC.
resource "google_dns_managed_zone" "googleapis" {
  project    = var.project_id
  name       = "${var.name}-googleapis"
  dns_name   = "googleapis.com."
  visibility = "private"
  labels     = var.labels

  private_visibility_config {
    networks {
      network_url = google_compute_network.this.id
    }
  }
}

resource "google_dns_record_set" "restricted_a" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.googleapis.name
  name         = "restricted.googleapis.com."
  type         = "A"
  ttl          = 300
  rrdatas      = ["199.36.153.4", "199.36.153.5", "199.36.153.6", "199.36.153.7"]
}

resource "google_dns_record_set" "restricted_cname" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.googleapis.name
  name         = "*.googleapis.com."
  type         = "CNAME"
  ttl          = 300
  rrdatas      = ["restricted.googleapis.com."]
}

resource "google_dns_managed_zone" "private" {
  count = var.private_zone == null ? 0 : 1

  project    = var.project_id
  name       = "${var.name}-${replace(var.private_zone, ".", "-")}"
  dns_name   = "${var.private_zone}."
  visibility = "private"
  labels     = var.labels

  private_visibility_config {
    networks {
      network_url = google_compute_network.this.id
    }
  }
}

resource "google_dns_managed_zone" "public" {
  for_each = toset(var.public_zones)

  project  = var.project_id
  name     = replace(each.value, ".", "-")
  dns_name = "${each.value}."
  labels   = var.labels

  dnssec_config {
    state = "on"
  }
}
