# One GKE cluster with its own node subnet (decisions #23): private nodes, DNS-based control-plane
# endpoint only (decisions #22), Dataplane V2, Workload Identity Federation, Binary Authorization,
# Shielded Nodes, Backup for GKE agent, Managed Prometheus, fleet registration (managed Istio).

locals {
  regional = var.cluster_type == "regional"
  location = local.regional ? var.region : var.zones[0]
  # Zonal control plane with node pools across zones: the cluster zone is implied, list the others.
  node_locations = local.regional ? var.zones : slice(var.zones, 1, length(var.zones))
}

resource "google_compute_subnetwork" "nodes" {
  project                  = var.host_project_id
  name                     = "snet-${var.name}"
  region                   = var.region
  network                  = var.network_id
  ip_cidr_range            = var.ranges.nodes
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "${var.name}-pods"
    ip_cidr_range = var.ranges.pods
  }
  secondary_ip_range {
    range_name    = "${var.name}-services"
    ip_cidr_range = var.ranges.services
  }

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Shared VPC: the service project's GKE and Google APIs agents use the subnet.
resource "google_compute_subnetwork_iam_member" "gke" {
  for_each = toset([
    "serviceAccount:service-${var.project_number}@container-engine-robot.iam.gserviceaccount.com",
    "serviceAccount:${var.project_number}@cloudservices.gserviceaccount.com",
  ])

  project    = var.host_project_id
  region     = var.region
  subnetwork = google_compute_subnetwork.nodes.name
  role       = "roles/compute.networkUser"
  member     = each.value
}

resource "google_container_cluster" "this" {
  project         = var.project_id
  name            = var.name
  location        = local.location
  node_locations  = local.node_locations
  resource_labels = var.labels

  network         = var.network_id
  subnetwork      = google_compute_subnetwork.nodes.id
  networking_mode = "VPC_NATIVE"

  ip_allocation_policy {
    cluster_secondary_range_name  = "${var.name}-pods"
    services_secondary_range_name = "${var.name}-services"
  }

  remove_default_node_pool  = true
  initial_node_count        = 1
  default_max_pods_per_node = var.max_pods_per_node
  datapath_provider         = "ADVANCED_DATAPATH"
  enable_shielded_nodes     = true
  deletion_protection       = var.deletion_protection

  release_channel {
    channel = var.release_channel
  }

  private_cluster_config {
    enable_private_nodes = true
  }

  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic = true # reached via Google APIs; IAM + VPC-SC decide who gets in
    }
    ip_endpoints_config {
      enabled = false
    }
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  binary_authorization {
    evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE"
  }

  security_posture_config {
    mode               = "BASIC"
    vulnerability_mode = "VULNERABILITY_BASIC"
  }

  addons_config {
    http_load_balancing {
      disabled = false
    }
    gce_persistent_disk_csi_driver_config {
      enabled = true
    }
    gcs_fuse_csi_driver_config {
      enabled = true
    }
    gke_backup_agent_config {
      enabled = true
    }
    dns_cache_config {
      enabled = true
    }
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus {
      enabled = true
    }
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  dynamic "database_encryption" {
    for_each = var.secrets_encryption_key == null ? [] : [var.secrets_encryption_key]
    content {
      state    = "ENCRYPTED"
      key_name = database_encryption.value
    }
  }

  maintenance_policy {
    recurring_window {
      start_time = "2026-01-04T02:00:00Z"
      end_time   = "2026-01-04T08:00:00Z"
      recurrence = var.maintenance_recurrence
    }
  }

  fleet {
    project = var.project_id
  }

  lifecycle {
    ignore_changes = [initial_node_count]
  }

  depends_on = [google_compute_subnetwork_iam_member.gke]
}

resource "google_container_node_pool" "pools" {
  for_each = var.node_pools

  project           = var.project_id
  name              = each.key
  cluster           = google_container_cluster.this.id
  location          = local.location
  node_locations    = local.node_locations
  max_pods_per_node = var.max_pods_per_node

  autoscaling {
    min_node_count  = each.value.min_nodes
    max_node_count  = each.value.max_nodes
    location_policy = "BALANCED"
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  upgrade_settings {
    strategy        = "SURGE"
    max_surge       = 1
    max_unavailable = 0
  }

  node_config {
    machine_type    = each.value.machine_type
    image_type      = "COS_CONTAINERD"
    disk_type       = "pd-balanced"
    disk_size_gb    = 100
    service_account = var.node_service_account
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    tags            = ["gke-node", "lb-backend", "gke-${var.name}"]
    resource_labels = var.labels
    labels          = { "platform.example/pool" = each.key }

    dynamic "taint" {
      for_each = each.value.taints
      content {
        key    = taint.value.key
        value  = taint.value.value
        effect = taint.value.effect
      }
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }

  lifecycle {
    ignore_changes = [initial_node_count]
  }
}
