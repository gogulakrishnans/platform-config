output "projects" {
  value = { for k, m in module.project : k => m.project_id }
}

output "management_clusters" {
  value = { for k, m in module.platform : k => m.mgmt_cluster }
}

output "registries" {
  value = { for k, m in module.platform : k => m.registries }
}

output "vpc_sc_perimeters" {
  value = module.vpc_sc.perimeters
}
