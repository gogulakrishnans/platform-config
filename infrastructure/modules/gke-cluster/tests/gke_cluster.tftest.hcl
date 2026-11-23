mock_provider "google" {}

variables {
  project_id      = "pfx-compute-prod"
  project_number  = "200000000005"
  host_project_id = "pfx-net-prod"
  network_id      = "projects/pfx-net-prod/global/networks/vpc-prod"
  name            = "prod-us-east1-01"
  region          = "us-east1"
  zones           = ["us-east1-b", "us-east1-c", "us-east1-d"]
  ranges = {
    nodes    = "10.110.1.0/24"
    pods     = "100.96.64.0/18"
    services = "100.102.4.0/22"
  }
  release_channel      = "STABLE"
  node_service_account = "gke-nodes@pfx-compute-prod.iam.gserviceaccount.com"
  node_pools           = { default = { machine_type = "n2-standard-8", min_nodes = 1, max_nodes = 20 } }
  labels = {
    customer = "shared", environment = "prod", "env-group" = "prod",
    product  = "platform", "region-role" = "primary", "managed-by" = "terraform"
  }
}

run "regional_private_cluster_with_dns_endpoint_only" {
  command = plan

  assert {
    condition     = google_container_cluster.this.location == "us-east1"
    error_message = "prod clusters are regional"
  }
  assert {
    condition     = google_container_cluster.this.control_plane_endpoints_config[0].ip_endpoints_config[0].enabled == false
    error_message = "IP endpoints are disabled (decisions #22)"
  }
  assert {
    condition     = google_container_cluster.this.private_cluster_config[0].enable_private_nodes == true
    error_message = "nodes are private"
  }
  assert {
    condition     = google_container_cluster.this.workload_identity_config[0].workload_pool == "pfx-compute-prod.svc.id.goog"
    error_message = "Workload Identity Federation is enabled"
  }
  assert {
    condition     = google_container_cluster.this.binary_authorization[0].evaluation_mode == "PROJECT_SINGLETON_POLICY_ENFORCE"
    error_message = "Binary Authorization is enforced"
  }
  assert {
    condition     = google_container_cluster.this.datapath_provider == "ADVANCED_DATAPATH"
    error_message = "Dataplane V2 (NetworkPolicy)"
  }
  assert {
    condition     = google_compute_subnetwork.nodes.name == "snet-prod-us-east1-01"
    error_message = "one node subnet per cluster (decisions #23)"
  }
  assert {
    condition     = google_container_node_pool.pools["default"].node_config[0].workload_metadata_config[0].mode == "GKE_METADATA"
    error_message = "node pools use the GKE metadata server"
  }
}

run "zonal_dev_stage_cluster_spreads_nodes" {
  command = plan

  variables {
    name            = "devstage-us-east1-01"
    cluster_type    = "zonal"
    release_channel = "RAPID"
  }

  assert {
    condition     = google_container_cluster.this.location == "us-east1-b"
    error_message = "zonal control plane"
  }
  assert {
    condition     = toset(google_container_cluster.this.node_locations) == toset(["us-east1-c", "us-east1-d"])
    error_message = "nodes in the other two zones as well"
  }
}
