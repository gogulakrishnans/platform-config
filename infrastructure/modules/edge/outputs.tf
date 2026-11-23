output "ip_address" {
  value = module.lb.ip_address
}

output "host_rules" {
  description = "Path matcher => hosts, default backend and path rules."
  value       = local.host_rules
}

output "backends" {
  value = keys(merge(local.istio_backends, local.workload_backends))
}
