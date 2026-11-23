mock_provider "google" {}

variables {
  project_id      = "pfx-compute-prod"
  display_name    = "compute-prod"
  folder_id       = "folders/100000000002"
  billing_account = "000000-000000-000000"
  labels = {
    customer = "shared", environment = "prod", "env-group" = "prod",
    product  = "platform", "region-role" = "primary", "managed-by" = "terraform"
  }
  services                = ["container.googleapis.com", "run.googleapis.com"]
  shared_vpc_host_project = "pfx-net-prod"
  audit_log_destination   = "logging.googleapis.com/projects/pfx-security-prod/locations/global/buckets/audit"
}

run "creates_project_with_guardrails" {
  command = plan

  assert {
    condition     = google_project.this.auto_create_network == false
    error_message = "no default network"
  }
  assert {
    condition     = google_project.this.deletion_policy == "PREVENT"
    error_message = "projects are protected by default"
  }
  assert {
    condition     = google_project.this.labels["managed-by"] == "terraform"
    error_message = "mandatory labels are applied"
  }
  assert {
    condition     = length(google_compute_shared_vpc_service_project.this) == 1 && length(google_compute_shared_vpc_host_project.this) == 0
    error_message = "attached as a Shared VPC service project"
  }
  assert {
    condition     = length(google_billing_budget.this.threshold_rules) == 3
    error_message = "budget alerts at 50/80/100%"
  }
  assert {
    condition     = length(google_logging_project_sink.audit) == 1
    error_message = "audit logs go to the central sink"
  }
}

run "rejects_missing_labels" {
  command = plan

  variables {
    labels = { customer = "shared" }
  }

  expect_failures = [var.labels]
}

run "rejects_long_project_id" {
  command = plan

  variables {
    project_id = "pfx-a-project-id-that-is-far-too-long"
  }

  expect_failures = [var.project_id]
}
