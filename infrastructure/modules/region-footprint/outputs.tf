output "clusters" {
  value = { for k, m in module.cluster : k => { id = m.id, location = m.location, endpoint = m.dns_endpoint } }
}

output "sql_instances" {
  value = { for k, m in module.sql : k => { connection_name = m.connection_name, write_endpoint = m.write_endpoint, dr = m.dr_name } }
}

output "nat_ips" {
  value = try(module.network_region[0].nat_ips, [])
}
