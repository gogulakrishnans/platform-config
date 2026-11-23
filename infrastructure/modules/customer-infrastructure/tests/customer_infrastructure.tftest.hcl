# Renders the two example customers end to end with mock providers (no credentials).

mock_provider "google" {}

variables {
  repo_root = "../../.."
}

run "acme_corp_prod_gke_and_cloud_run_with_pubsub" {
  command = plan

  variables {
    customer    = "acme-corp"
    environment = "prod"
  }

  assert {
    condition     = google_service_account.env.account_id == "acme-corp-prod" && google_service_account.env.project == "pfx-compute-prod"
    error_message = "one env GSA per customer per environment, in the group's compute project"
  }
  assert {
    condition     = module.database.database == "acme_corp_prod"
    error_message = "database per customer per environment, hyphens -> underscores"
  }
  assert {
    condition     = output.bootstrap.instance == "sql-prod-us-east1-01" && output.bootstrap.schemas == tolist(["payment", "reporting"])
    error_message = "prod DB on the cell's own instance, one schema per product"
  }
  assert {
    condition     = output.buckets == { "payment-api" = "pfx-acme-corp-payment-prod", "reporting-engine" = "pfx-acme-corp-reporting-prod" }
    error_message = "one bucket per customer x product x env"
  }
  assert {
    condition     = module.bucket["payment-api"].name == "pfx-acme-corp-payment-prod"
    error_message = "bucket module receives the computed name"
  }
  assert {
    condition     = output.datasets == { "reporting-engine" = "acme_corp_reporting_prod" }
    error_message = "datasets only where the catalog requires them"
  }
  assert {
    condition     = module.dataset["reporting-engine"].dr_dataset_id == "acme_corp_reporting_prod_dr"
    error_message = "prod datasets get a DR dataset in the pair region"
  }
  assert {
    condition     = output.topics == { "payment-events" = "acme-corp-payment-prod-events" }
    error_message = "GKE payment-api publishes its events topic"
  }
  assert {
    condition     = output.subscriptions == ["acme-corp-reporting-prod-from-payment-events"]
    error_message = "Cloud Run reporting-engine subscribes"
  }
  assert {
    condition     = keys(module.cloud_run) == ["reporting-engine"] && keys(module.cloud_run_dr) == ["reporting-engine"]
    error_message = "Cloud Run service in the primary region and a DR copy in the pair region"
  }
  assert {
    condition     = length(module.mig) == 0
    error_message = "no MIG products for acme-corp"
  }
  assert {
    condition     = length(google_service_account_iam_member.workload_identity) == 1
    error_message = "the GKE product KSA can impersonate the env GSA (Cloud SQL login)"
  }
  assert {
    condition     = length(module.backup_plan) == 1
    error_message = "Backup for GKE plan for the customer namespace"
  }
  assert {
    condition     = output.labels["payment/dr"]["region-role"] == "dr" && output.labels["platform/primary"].customer == "acme-corp"
    error_message = "mandatory labels with region role"
  }
}

run "acme_corp_dev_has_no_dr_and_regional_storage" {
  command = plan

  variables {
    customer    = "acme-corp"
    environment = "dev"
  }

  assert {
    condition     = google_service_account.env.project == "pfx-compute-devstage"
    error_message = "dev identities live in compute-devstage"
  }
  assert {
    condition     = output.bootstrap.instance == "sql-nonprod-us-east1-01" && output.bootstrap.database == "acme_corp_dev"
    error_message = "dev database on the regional non-prod instance"
  }
  assert {
    condition     = length(module.cloud_run_dr) == 0 && module.dataset["reporting-engine"].dr_dataset_id == null
    error_message = "no DR copies outside prod"
  }
  assert {
    condition     = output.namespace == "acme-corp-dev"
    error_message = "namespace {customer}-{env}"
  }
}

run "beta_industries_prod_mig_with_dr" {
  command = plan

  variables {
    customer    = "beta-industries"
    environment = "prod"
  }

  assert {
    condition     = output.migs == { "legacy-billing" = "beta-industries-billing-prod" }
    error_message = "regional MIG per customer x product x env"
  }
  assert {
    condition     = keys(module.mig_dr) == ["legacy-billing"]
    error_message = "MIG DR copy in the pair region"
  }
  assert {
    condition     = length(google_project_iam_member.mig_observability) == 2
    error_message = "MIG identities get only the allowlisted logWriter/metricWriter project roles"
  }
  assert {
    condition     = output.bootstrap.instance == "sql-prod-us-central1-01"
    error_message = "beta-industries is placed in us-central1"
  }
  assert {
    condition     = length(module.cloud_run) == 0 && output.topics == { "payment-events" = "beta-industries-payment-prod-events" } && length(output.subscriptions) == 0
    error_message = "no Cloud Run products; payment-api publishes with no subscribers"
  }
}

run "rejects_unknown_environment" {
  command = plan

  variables {
    customer    = "acme-corp"
    environment = "qa"
  }

  expect_failures = [var.environment]
}
