output "id" {
  value = google_container_cluster.this.id
}

output "name" {
  value = google_container_cluster.this.name
}

output "location" {
  value = google_container_cluster.this.location
}

output "dns_endpoint" {
  description = "DNS-based control-plane endpoint (recorded in inventory/clusters, used by ArgoCD)."
  value       = try(google_container_cluster.this.control_plane_endpoints_config[0].dns_endpoint_config[0].endpoint, null)
}

output "subnet" {
  value = google_compute_subnetwork.nodes.self_link
}

output "workload_pool" {
  value = "${var.project_id}.svc.id.goog"
}
