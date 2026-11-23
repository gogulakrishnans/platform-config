output "name" {
  value = google_sql_database_instance.primary.name
}

output "connection_name" {
  value = google_sql_database_instance.primary.connection_name
}

output "write_endpoint" {
  description = "DNS write endpoint (follows the primary across switchover/failover)."
  value       = try(google_sql_database_instance.primary.dns_names[0].name, null)
}

output "private_ip" {
  value = google_sql_database_instance.primary.private_ip_address
}

output "dr_name" {
  value = try(google_sql_database_instance.dr[0].name, null)
}
