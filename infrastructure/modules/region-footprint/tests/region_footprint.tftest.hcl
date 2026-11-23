mock_provider "google" {}
mock_provider "local" {}

variables {
  repo_root = "../../.."
  region    = "us-east1"
}

run "prod_builds_cell_dr_cluster_and_replicated_instance" {
  command = plan

  variables {
    group = "prod"
  }

  assert {
    condition     = toset(keys(module.cluster)) == toset(["prod-us-east1-01", "prod-us-east1-01-dr"])
    error_message = "prod cell plus its dedicated DR cluster"
  }
  assert {
    condition     = keys(module.sql) == ["sql-prod-us-east1-01"]
    error_message = "one prod instance per prod cell"
  }
  assert {
    condition     = length(module.network_region) == 1 && length(module.seed_work_bucket) == 1
    error_message = "the prod state owns the prod side's regional network and the seed work bucket"
  }
  assert {
    condition     = keys(local_file.cluster_inventory) == ["prod-us-east1-01"]
    error_message = "L2 writes the cell inventory (DR details embedded)"
  }
}

run "devstage_builds_two_zonal_cells_and_the_nonprod_instance" {
  command = plan

  variables {
    group = "devstage"
  }

  assert {
    condition     = toset(keys(module.cluster)) == toset(["devstage-us-east1-01", "devstage-us-east1-02"])
    error_message = "two dev/stage cells in us-east1"
  }
  assert {
    condition     = keys(module.sql) == ["sql-nonprod-us-east1-01"]
    error_message = "the devstage state owns the regional non-prod instance pool"
  }
}

run "uat_does_not_own_shared_network_or_instances" {
  command = plan

  variables {
    group = "uat"
  }

  assert {
    condition     = length(module.network_region) == 0 && length(module.sql) == 0 && length(google_cloud_run_v2_job.db_bootstrap) == 0
    error_message = "the non-prod side's shared pieces are owned by the devstage state"
  }
  assert {
    condition     = keys(module.cluster) == ["uat-us-east1-01"]
    error_message = "one UAT cell"
  }
}
