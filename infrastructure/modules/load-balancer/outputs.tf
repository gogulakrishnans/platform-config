output "ip_address" {
  value = local.external ? google_compute_global_address.this[0].address : google_compute_address.internal[0].address
}

output "backend_services" {
  value = local.backend_ids
}

output "url_map" {
  value = local.external ? google_compute_url_map.this[0].id : google_compute_region_url_map.this[0].id
}
