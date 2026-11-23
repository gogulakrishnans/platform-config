# Application Load Balancer, global external (UAT, Prod) or regional internal (Dev/Stage), with
# backend services, health checks, a host/path URL map and TLS (architecture §11).
# Backends reference resources created elsewhere by deterministic names (C14):
#   neg        zonal NEGs of the Istio ingress gateway (GKE)
#   serverless serverless NEGs of Cloud Run services
#   mig        regional managed instance groups

locals {
  external = var.scheme == "EXTERNAL_MANAGED"
  scheme   = var.scheme
  with_hc  = { for k, b in var.backends : k => b if b.kind != "serverless" }
  balancing = {
    neg        = "RATE"
    mig        = "UTILIZATION"
    serverless = null
  }
}

# ------------------------------------------------------------------------------- health checks

resource "google_compute_health_check" "this" {
  for_each = local.external ? local.with_hc : {}

  project = var.project_id
  name    = "hc-lb-${each.key}"

  dynamic "http_health_check" {
    for_each = each.value.health_check.protocol == "HTTP" ? [each.value.health_check] : []
    content {
      port         = http_health_check.value.port
      request_path = http_health_check.value.path
    }
  }
  dynamic "https_health_check" {
    for_each = each.value.health_check.protocol == "HTTPS" ? [each.value.health_check] : []
    content {
      port         = https_health_check.value.port
      request_path = https_health_check.value.path
    }
  }
}

resource "google_compute_region_health_check" "this" {
  for_each = local.external ? {} : local.with_hc

  project = var.project_id
  region  = var.region
  name    = "hc-lb-${each.key}"

  dynamic "http_health_check" {
    for_each = each.value.health_check.protocol == "HTTP" ? [each.value.health_check] : []
    content {
      port         = http_health_check.value.port
      request_path = http_health_check.value.path
    }
  }
  dynamic "https_health_check" {
    for_each = each.value.health_check.protocol == "HTTPS" ? [each.value.health_check] : []
    content {
      port         = https_health_check.value.port
      request_path = https_health_check.value.path
    }
  }
}

# ------------------------------------------------------------------------------- backend services

resource "google_compute_backend_service" "this" {
  for_each = local.external ? var.backends : {}

  project                         = var.project_id
  name                            = "be-${each.key}"
  load_balancing_scheme           = local.scheme
  protocol                        = "HTTPS"
  timeout_sec                     = 30
  connection_draining_timeout_sec = each.value.kind == "serverless" ? null : 30
  enable_cdn                      = each.value.enable_cdn
  security_policy                 = var.security_policy
  health_checks                   = each.value.kind == "serverless" ? null : [google_compute_health_check.this[each.key].id]

  dynamic "backend" {
    for_each = each.value.groups
    content {
      group                 = backend.value.group
      balancing_mode        = local.balancing[each.value.kind]
      capacity_scaler       = each.value.kind == "serverless" ? null : backend.value.capacity_scaler
      max_rate_per_endpoint = each.value.kind == "neg" ? 500 : null
      max_utilization       = each.value.kind == "mig" ? 0.8 : null
    }
  }

  log_config {
    enable      = true
    sample_rate = 1
  }
}

resource "google_compute_region_backend_service" "this" {
  for_each = local.external ? {} : var.backends

  project                         = var.project_id
  region                          = var.region
  name                            = "be-${each.key}"
  load_balancing_scheme           = local.scheme
  protocol                        = "HTTPS"
  timeout_sec                     = 30
  connection_draining_timeout_sec = each.value.kind == "serverless" ? null : 30
  health_checks                   = each.value.kind == "serverless" ? null : [google_compute_region_health_check.this[each.key].id]

  dynamic "backend" {
    for_each = each.value.groups
    content {
      group                 = backend.value.group
      balancing_mode        = local.balancing[each.value.kind]
      capacity_scaler       = each.value.kind == "serverless" ? null : backend.value.capacity_scaler
      max_rate_per_endpoint = each.value.kind == "neg" ? 500 : null
      max_utilization       = each.value.kind == "mig" ? 0.8 : null
    }
  }

  dynamic "iap" {
    for_each = var.iap ? [1] : []
    content {
      enabled = true
    }
  }
}

locals {
  backend_ids = local.external ? { for k, b in google_compute_backend_service.this : k => b.id } : { for k, b in google_compute_region_backend_service.this : k => b.id }
}

# ------------------------------------------------------------------------------- URL maps

resource "google_compute_url_map" "this" {
  count = local.external ? 1 : 0

  project = var.project_id
  name    = "um-${var.name}"

  default_url_redirect {
    host_redirect          = var.default_redirect_host
    https_redirect         = true
    strip_query            = true
    redirect_response_code = "FOUND"
  }

  dynamic "host_rule" {
    for_each = var.host_rules
    content {
      hosts        = host_rule.value.hosts
      path_matcher = host_rule.key
    }
  }

  dynamic "path_matcher" {
    for_each = var.host_rules
    content {
      name            = path_matcher.key
      default_service = local.backend_ids[path_matcher.value.default_backend]

      dynamic "path_rule" {
        for_each = path_matcher.value.paths
        content {
          paths   = path_rule.value.paths
          service = local.backend_ids[path_rule.value.backend]
        }
      }
    }
  }
}

resource "google_compute_region_url_map" "this" {
  count = local.external ? 0 : 1

  project = var.project_id
  region  = var.region
  name    = "um-${var.name}"

  default_url_redirect {
    host_redirect          = var.default_redirect_host
    https_redirect         = true
    strip_query            = true
    redirect_response_code = "FOUND"
  }

  dynamic "host_rule" {
    for_each = var.host_rules
    content {
      hosts        = host_rule.value.hosts
      path_matcher = host_rule.key
    }
  }

  dynamic "path_matcher" {
    for_each = var.host_rules
    content {
      name            = path_matcher.key
      default_service = local.backend_ids[path_matcher.value.default_backend]

      dynamic "path_rule" {
        for_each = path_matcher.value.paths
        content {
          paths   = path_rule.value.paths
          service = local.backend_ids[path_rule.value.backend]
        }
      }
    }
  }
}

# ------------------------------------------------------------------------------- frontends

resource "google_compute_ssl_policy" "this" {
  count = local.external ? 1 : 0

  project         = var.project_id
  name            = "tls-${var.name}"
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"
}

resource "google_compute_global_address" "this" {
  count = local.external ? 1 : 0

  project = var.project_id
  name    = "ip-${var.name}"
  labels  = var.labels
}

resource "google_compute_target_https_proxy" "this" {
  count = local.external ? 1 : 0

  project         = var.project_id
  name            = "tp-${var.name}"
  url_map         = google_compute_url_map.this[0].id
  certificate_map = "//certificatemanager.googleapis.com/${var.certificate_map}"
  ssl_policy      = google_compute_ssl_policy.this[0].id
}

resource "google_compute_global_forwarding_rule" "https" {
  count = local.external ? 1 : 0

  project               = var.project_id
  name                  = "fr-${var.name}-https"
  ip_address            = google_compute_global_address.this[0].id
  port_range            = "443"
  target                = google_compute_target_https_proxy.this[0].id
  load_balancing_scheme = local.scheme
  labels                = var.labels
}

resource "google_compute_url_map" "redirect" {
  count = local.external ? 1 : 0

  project = var.project_id
  name    = "um-${var.name}-redirect"

  default_url_redirect {
    https_redirect = true
    strip_query    = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  count = local.external ? 1 : 0

  project = var.project_id
  name    = "tp-${var.name}-http"
  url_map = google_compute_url_map.redirect[0].id
}

resource "google_compute_global_forwarding_rule" "http" {
  count = local.external ? 1 : 0

  project               = var.project_id
  name                  = "fr-${var.name}-http"
  ip_address            = google_compute_global_address.this[0].id
  port_range            = "80"
  target                = google_compute_target_http_proxy.redirect[0].id
  load_balancing_scheme = local.scheme
  labels                = var.labels
}

resource "google_compute_address" "internal" {
  count = local.external ? 0 : 1

  project      = var.project_id
  region       = var.region
  name         = "ip-${var.name}"
  address_type = "INTERNAL"
  subnetwork   = var.subnetwork
  labels       = var.labels
}

resource "google_compute_region_target_https_proxy" "this" {
  count = local.external ? 0 : 1

  project                          = var.project_id
  region                           = var.region
  name                             = "tp-${var.name}"
  url_map                          = google_compute_region_url_map.this[0].id
  certificate_manager_certificates = var.certificates
}

resource "google_compute_forwarding_rule" "internal" {
  count = local.external ? 0 : 1

  project               = var.project_id
  region                = var.region
  name                  = "fr-${var.name}-https"
  ip_address            = google_compute_address.internal[0].id
  port_range            = "443"
  target                = google_compute_region_target_https_proxy.this[0].id
  load_balancing_scheme = local.scheme
  network               = var.network
  subnetwork            = var.subnetwork
  labels                = var.labels
}
