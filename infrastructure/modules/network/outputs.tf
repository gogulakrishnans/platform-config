output "network_id" {
  value = google_compute_network.this.id
}

output "network_self_link" {
  value = google_compute_network.this.self_link
}

output "name" {
  value = google_compute_network.this.name
}

output "psa_range_names" {
  value = { for k, a in google_compute_global_address.psa : k => a.name }
}

output "public_zone_names" {
  value = { for k, z in google_dns_managed_zone.public : k => z.name }
}

output "private_zone_name" {
  value = try(google_dns_managed_zone.private[0].name, null)
}
