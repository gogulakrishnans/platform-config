variables {
  repo_root = "../../.."
}

run "reads_the_repository_registry" {
  command = plan

  assert {
    condition     = length(output.projects) == 12
    error_message = "the fixed project model has 12 projects"
  }
  assert {
    condition     = keys(output.active_regions) == ["us-central1", "us-east1"]
    error_message = "only active regions are returned"
  }
  assert {
    condition     = contains(keys(output.customers), "acme-corp") && contains(keys(output.customers), "beta-industries")
    error_message = "example customers are loaded"
  }
}

run "ip_plan_matches_architecture" {
  command = plan

  assert {
    condition     = output.ip_plan["us-east1"].nonprod.run == "10.10.32.0/20"
    error_message = "Cloud Run egress subnet must be x.x.32.0/20"
  }
  assert {
    condition     = output.ip_plan["us-east1"].prod.psa == "10.110.64.0/18"
    error_message = "PSA allocation must be x.x.64.0/18"
  }
  assert {
    condition     = output.ip_plan["us-east1"].prod.proxy == "10.110.52.0/23"
    error_message = "proxy-only subnet must be x.x.52.0/23"
  }
}

run "cluster_plan_includes_cells_dr_and_management" {
  command = plan

  assert {
    condition     = output.cluster_plan["prod-us-east1-01-dr"].region == "us-central1"
    error_message = "the DR cluster of a us-east1 cell lives in the pair region"
  }
  assert {
    condition     = output.cluster_plan["prod-us-east1-01"].nodes_cidr == "10.110.1.0/24"
    error_message = "slot 1 node range"
  }
  assert {
    condition     = output.cluster_plan["prod-us-east1-01"].pods_cidr == "100.96.64.0/18"
    error_message = "slot 1 pod range"
  }
  assert {
    condition     = output.cluster_plan["prod-us-east1-01"].services_cidr == "100.102.4.0/22"
    error_message = "slot 1 service range"
  }
  assert {
    condition     = output.cluster_plan["mgmt-prod"].project_key == "platform-prod"
    error_message = "management cluster lives in platform-prod"
  }
  assert {
    condition     = length(output.cluster_plan) == 11
    error_message = "4 + 3 cells, 2 DR clusters and 2 management clusters"
  }
}

run "sql_plan_has_one_prod_instance_per_cell_with_dr" {
  command = plan

  assert {
    condition     = output.sql_plan["sql-prod-us-east1-01"].dr.region == "us-central1"
    error_message = "prod instance replica in the DR pair"
  }
  assert {
    condition     = output.sql_plan["sql-nonprod-us-east1-01"].dr == null
    error_message = "non-prod instances have no DR replica"
  }
}
