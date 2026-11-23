# L2 edge composition (clarification C14): one load balancer per environment group, built from Git.
#   prod      global external ALB + Cloud Armor + per-customer certificates (apex + wildcard, V8)
#   uat       global external ALB + Cloud Armor IP allowlist + one *.uat wildcard certificate
#   devstage  regional internal ALB per region + IAP + CAS-issued certificate (private DNS)
# Backends reference Istio gateway NEGs, Cloud Run serverless NEGs and MIGs by deterministic names;
# DR backends carry capacity 0 until the cell's drActive flag flips (decisions #25).

module "registry" {
  source    = "../registry"
  repo_root = var.repo_root
}

locals {
  reg       = module.registry
  group     = var.group
  external  = local.group != "devstage"
  gcfg      = local.reg.platform.groups[local.group]
  side      = local.gcfg.side
  envs      = local.gcfg.environments
  edge      = local.reg.platform.edge
  dns       = local.reg.platform.dns
  name      = local.external ? "${local.group}-edge" : "devstage-${var.region}"
  compute   = local.reg.projects[local.gcfg.computeProject]
  host      = local.reg.projects["net-${local.side}"]
  security  = local.reg.projects[local.gcfg.securityProject]
  api       = "https://www.googleapis.com/compute/v1/projects/${local.compute}"
  hub       = local.reg.platform.hubRegion
  public    = local.group == "prod" ? local.dns.publicZone : local.dns.uatZone
  zone_name = local.external ? replace(local.public, ".", "-") : "vpc-nonprod-${replace(local.dns.privateZone, ".", "-")}"

  customers = {
    for c, cu in local.reg.customers : c => cu.spec
    if try(cu.spec.options.isolation, "shared") == "shared"
    && try(cu.spec.placement[local.group], null) != null
    && (local.external || cu.spec.region.primary == var.region)
  }

  cells = {
    for k, c in local.reg.cluster_plan : k => c
    if c.group == local.group && c.role == "primary" && (local.external || c.region == var.region)
  }

  # ---------------------------------------------------------------- backends
  istio_backends = {
    for k, c in local.cells : "istio-${k}" => {
      kind       = "neg"
      enable_cdn = local.group == "prod"
      health_check = {
        protocol = "HTTP"
        port     = 15021
        path     = "/healthz/ready"
      }
      groups = concat(
        [for z in c.zones : { group = "${local.api}/zones/${z}/networkEndpointGroups/neg-istio-${k}", capacity_scaler = c.dr_active ? 0 : 1 }],
        local.group == "prod" ? [for z in local.reg.cluster_plan["${k}-dr"].zones : {
          group           = "${local.api}/zones/${z}/networkEndpointGroups/neg-istio-${k}-dr"
          capacity_scaler = c.dr_active ? 1 : 0
        }] : [],
      )
    }
  }

  workloads = flatten([for c, spec in local.customers : [
    for e in local.envs : [
      for p, cfg in local.reg.customer_products[c] : {
        key       = "${c}-${local.reg.products[p].spec.shortCode}-${e}"
        customer  = c
        env       = e
        product   = p
        kind      = local.reg.products[p].spec.runtime.type
        region    = spec.region.primary
        pair      = local.reg.regions[spec.region.primary].drPair
        dr_active = local.group == "prod" ? local.reg.cluster_plan[spec.placement.prod.cluster].dr_active : false
        paths     = try(local.reg.products[p].spec.routing.paths, [])
        port      = try(local.reg.products[p].spec.runtime.port, 8443)
        hc_path   = try(local.reg.products[p].spec.runtime.healthCheckPath, "/healthz/ready")
      } if local.reg.products[p].spec.runtime.type != "gke"
    ]
  ]])

  workload_backends = {
    for w in local.workloads : w.key => w.kind == "cloud-run" ? {
      kind         = "serverless"
      enable_cdn   = false
      health_check = null
      groups       = [{ group = "${local.api}/regions/${w.dr_active ? w.pair : w.region}/networkEndpointGroups/neg-${w.key}", capacity_scaler = 1 }]
      } : {
      kind       = "mig"
      enable_cdn = false
      health_check = {
        protocol = "HTTPS"
        port     = w.port
        path     = w.hc_path
      }
      groups = concat(
        [{ group = "${local.api}/regions/${w.region}/instanceGroups/${w.key}", capacity_scaler = w.dr_active ? 0 : 1 }],
        local.group == "prod" ? [{ group = "${local.api}/regions/${w.pair}/instanceGroups/${w.key}", capacity_scaler = w.dr_active ? 1 : 0 }] : [],
      )
    }
  }

  # ---------------------------------------------------------------- host rules
  hosts = {
    for x in flatten([for c, spec in local.customers : [for e in local.envs : {
      key = "pm-${c}-${e}"
      c   = c
      e   = e
      hosts = local.group == "prod" ? compact([
        "${c}.${local.public}", "*.${c}.${local.public}", try(spec.options.edge.customDomain, null)
      ]) : (local.group == "uat" ? ["${c}.${local.public}"] : ["${c}.${e}.${local.dns.privateZone}"])
      has_gke = anytrue([for p in keys(local.reg.customer_products[c]) : local.reg.products[p].spec.runtime.type == "gke"])
      cell    = spec.placement[local.group].cluster
    }]]) : x.key => x
  }

  host_rules = {
    for k, h in local.hosts : k => {
      hosts = h.hosts
      default_backend = h.has_gke ? "istio-${h.cell}" : one([
        for w in local.workloads : w.key if w.customer == h.c && w.env == h.e
      ])
      paths = [for w in local.workloads : { paths = w.paths, backend = w.key }
      if w.customer == h.c && w.env == h.e && length(w.paths) > 0]
    }
  }
}

module "labels" {
  source = "../labels"

  environment = length(local.envs) == 1 ? local.envs[0] : "shared"
  env_group   = local.group
}

# ------------------------------------------------------------------ Cloud Armor (global edges)

resource "google_compute_security_policy" "this" {
  count = local.external ? 1 : 0

  project     = local.compute
  name        = "ca-${local.name}"
  description = "Cloud Armor for ${local.group}: WAF, DDoS, rate limits${local.group == "uat" ? ", IP allowlist" : ""}"
  labels      = module.labels.labels

  adaptive_protection_config {
    layer_7_ddos_defense_config {
      enable = true
    }
  }

  dynamic "rule" {
    for_each = local.group == "uat" ? [1] : []
    content {
      priority    = 900
      action      = "allow"
      description = "UAT testers allowlist"
      match {
        versioned_expr = "SRC_IPS_V1"
        config {
          src_ip_ranges = local.edge.uatAllowlist
        }
      }
    }
  }

  dynamic "rule" {
    for_each = {
      1000 = "sqli-v33-stable"
      1001 = "xss-v33-stable"
      1002 = "lfi-v33-stable"
      1003 = "rce-v33-stable"
      1004 = "protocolattack-v33-stable"
      1005 = "scannerdetection-v33-stable"
    }
    content {
      priority    = rule.key
      action      = "deny(403)"
      description = "OWASP CRS ${rule.value}"
      match {
        expr {
          expression = "evaluatePreconfiguredWaf('${rule.value}', {'sensitivity': 1})"
        }
      }
    }
  }

  dynamic "rule" {
    for_each = length(local.edge.blockedRegionCodes) > 0 ? [1] : []
    content {
      priority    = 1100
      action      = "deny(403)"
      description = "Geo-blocking"
      match {
        expr {
          expression = join(" || ", [for r in local.edge.blockedRegionCodes : "origin.region_code == '${r}'"])
        }
      }
    }
  }

  rule {
    priority    = 2000
    action      = "throttle"
    description = "Rate limit per client IP"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = local.edge.rateLimit.perClientIpPerMinute
        interval_sec = 60
      }
    }
  }

  rule {
    priority    = 2100
    action      = "throttle"
    description = "Rate limit per customer (Host header)"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action      = "allow"
      exceed_action       = "deny(429)"
      enforce_on_key      = "HTTP_HEADER"
      enforce_on_key_name = "host"
      rate_limit_threshold {
        count        = local.edge.rateLimit.perCustomerPerMinute
        interval_sec = 60
      }
    }
  }

  rule {
    priority    = 2147483647
    action      = local.group == "uat" ? "deny(403)" : "allow"
    description = "Default rule"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}

# ------------------------------------------------------------------ certificates

resource "google_certificate_manager_certificate_map" "this" {
  count = local.external ? 1 : 0

  project = local.compute
  name    = "cm-${local.name}"
  labels  = module.labels.labels
}

# Prod: one Google-managed certificate per customer covering the apex and the wildcard (V8).
resource "google_certificate_manager_dns_authorization" "customer" {
  for_each = local.group == "prod" ? local.customers : {}

  project = local.compute
  name    = "da-${each.key}"
  domain  = "${each.key}.${local.public}"
  labels  = module.labels.labels
}

resource "google_certificate_manager_certificate" "customer" {
  for_each = local.group == "prod" ? local.customers : {}

  project = local.compute
  name    = "cert-${each.key}"
  labels  = merge(module.labels.labels, { customer = each.key })

  managed {
    domains            = ["${each.key}.${local.public}", "*.${each.key}.${local.public}"]
    dns_authorizations = [google_certificate_manager_dns_authorization.customer[each.key].id]
  }
}

resource "google_certificate_manager_certificate_map_entry" "customer" {
  for_each = local.group == "prod" ? {
    for x in flatten([for c in keys(local.customers) : [
      { key = "${c}-apex", c = c, host = "${c}.${local.public}" },
      { key = "${c}-wildcard", c = c, host = "*.${c}.${local.public}" },
    ]]) : x.key => x
  } : {}

  project      = local.compute
  name         = each.key
  map          = google_certificate_manager_certificate_map.this[0].name
  hostname     = each.value.host
  certificates = [google_certificate_manager_certificate.customer[each.value.c].id]
  labels       = merge(module.labels.labels, { customer = each.value.c })
}

# UAT: one wildcard certificate for every customer.
resource "google_certificate_manager_dns_authorization" "uat" {
  count = local.group == "uat" ? 1 : 0

  project = local.compute
  name    = "da-uat"
  domain  = local.public
  labels  = module.labels.labels
}

resource "google_certificate_manager_certificate" "uat" {
  count = local.group == "uat" ? 1 : 0

  project = local.compute
  name    = "cert-uat-wildcard"
  labels  = module.labels.labels

  managed {
    domains            = ["*.${local.public}"]
    dns_authorizations = [google_certificate_manager_dns_authorization.uat[0].id]
  }
}

resource "google_certificate_manager_certificate_map_entry" "uat" {
  count = local.group == "uat" ? 1 : 0

  project      = local.compute
  name         = "uat-wildcard"
  map          = google_certificate_manager_certificate_map.this[0].name
  hostname     = "*.${local.public}"
  certificates = [google_certificate_manager_certificate.uat[0].id]
  labels       = module.labels.labels
}

# Dev/Stage: regional certificate issued by the private CA (CAS) for *.dev and *.stage.
resource "google_certificate_manager_certificate_issuance_config" "internal" {
  count = local.external ? 0 : 1

  project                    = local.compute
  name                       = "cic-${local.name}"
  location                   = var.region
  key_algorithm              = "ECDSA_P256"
  lifetime                   = "2592000s"
  rotation_window_percentage = 66
  labels                     = module.labels.labels

  certificate_authority_config {
    certificate_authority_service_config {
      ca_pool = "projects/${local.security}/locations/${local.hub}/caPools/${local.edge.internalCaPool}"
    }
  }
}

resource "google_certificate_manager_certificate" "internal" {
  count = local.external ? 0 : 1

  project  = local.compute
  name     = "cert-${local.name}"
  location = var.region
  labels   = module.labels.labels

  managed {
    domains         = [for e in local.envs : "*.${e}.${local.dns.privateZone}"]
    issuance_config = google_certificate_manager_certificate_issuance_config.internal[0].id
  }
}

# ------------------------------------------------------------------ load balancer

module "lb" {
  source = "../load-balancer"

  project_id            = local.compute
  name                  = local.name
  scheme                = local.external ? "EXTERNAL_MANAGED" : "INTERNAL_MANAGED"
  region                = local.external ? null : var.region
  network               = local.external ? null : "projects/${local.host}/global/networks/vpc-${local.side}"
  subnetwork            = local.external ? null : "projects/${local.host}/regions/${var.region}/subnetworks/snet-ops-${var.region}"
  backends              = merge(local.istio_backends, local.workload_backends)
  host_rules            = local.host_rules
  default_redirect_host = local.external ? local.public : "portal.${local.dns.privateZone}"
  certificate_map       = local.external ? google_certificate_manager_certificate_map.this[0].id : null
  certificates          = local.external ? [] : [google_certificate_manager_certificate.internal[0].id]
  security_policy       = local.external ? google_compute_security_policy.this[0].id : null
  iap                   = !local.external
  labels                = module.labels.labels
}

# ------------------------------------------------------------------ DNS

resource "google_dns_record_set" "authorization" {
  for_each = merge(
    { for c, d in google_certificate_manager_dns_authorization.customer : c => d },
    { for i, d in google_certificate_manager_dns_authorization.uat : "uat" => d },
  )

  project      = local.host
  managed_zone = local.zone_name
  name         = each.value.dns_resource_record[0].name
  type         = each.value.dns_resource_record[0].type
  ttl          = 300
  rrdatas      = [each.value.dns_resource_record[0].data]
}

resource "google_dns_record_set" "hosts" {
  for_each = local.group == "uat" ? { "*.${local.public}." = true } : merge([
    for h in values(local.hosts) : { for n in h.hosts : "${n}." => true if n != coalesce(try(local.customers[h.c].options.edge.customDomain, null), "~none~") } # custom domains are CNAMEd by the customer
  ]...)

  project      = local.host
  managed_zone = local.zone_name
  name         = each.key
  type         = "A"
  ttl          = 300
  rrdatas      = [module.lb.ip_address]
}
