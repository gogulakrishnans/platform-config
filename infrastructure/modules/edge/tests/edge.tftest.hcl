mock_provider "google" {}

variables {
  repo_root = "../../.."
}

run "prod_edge_routes_each_customer_to_its_cell_and_products" {
  command = plan

  variables {
    group = "prod"
  }

  assert {
    condition     = output.host_rules["pm-acme-corp-prod"].hosts == tolist(["acme-corp.platform.example", "*.acme-corp.platform.example"])
    error_message = "apex and wildcard hosts per customer"
  }
  assert {
    condition     = output.host_rules["pm-acme-corp-prod"].default_backend == "istio-prod-us-east1-01"
    error_message = "GKE products are reached through the cell's Istio gateway"
  }
  assert {
    condition     = output.host_rules["pm-acme-corp-prod"].paths[0].backend == "acme-corp-reporting-prod"
    error_message = "Cloud Run product paths go to its serverless NEG backend"
  }
  assert {
    condition     = output.host_rules["pm-beta-industries-prod"].default_backend == "istio-prod-us-central1-01"
    error_message = "beta-industries routes to its us-central1 cell"
  }
  assert {
    condition     = contains(output.backends, "beta-industries-billing-prod")
    error_message = "MIG product backend"
  }
  assert {
    condition     = length(google_certificate_manager_certificate.customer) == 2 && length(google_certificate_manager_certificate_map_entry.customer) == 4
    error_message = "one certificate (apex + wildcard) and two map entries per customer"
  }
  assert {
    condition     = length(google_compute_security_policy.this) == 1
    error_message = "Cloud Armor on the prod edge"
  }
}

run "uat_edge_uses_one_wildcard_and_an_allowlist" {
  command = plan

  variables {
    group = "uat"
  }

  assert {
    condition     = output.host_rules["pm-acme-corp-uat"].hosts == tolist(["acme-corp.uat.platform.example"])
    error_message = "UAT public hostnames (clarification C5)"
  }
  assert {
    condition     = length(google_certificate_manager_certificate.uat) == 1 && length(google_certificate_manager_certificate.customer) == 0
    error_message = "one wildcard certificate for UAT"
  }
}

run "devstage_edge_is_internal_per_region" {
  command = plan

  variables {
    group  = "devstage"
    region = "us-east1"
  }

  assert {
    condition     = toset(keys(output.host_rules)) == toset(["pm-acme-corp-dev", "pm-acme-corp-stage"])
    error_message = "only customers homed in us-east1, one host rule per environment"
  }
  assert {
    condition     = output.host_rules["pm-acme-corp-dev"].hosts == tolist(["acme-corp.dev.platform.internal"])
    error_message = "private hostnames for dev/stage"
  }
  assert {
    condition     = length(google_compute_security_policy.this) == 0
    error_message = "no internet exposure for dev/stage"
  }
}
