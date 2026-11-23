# Git is the registry (architecture §1). This module reads the YAML registry and derives the
# values every layer needs: project IDs/numbers, regions, the IP plan, the cluster and SQL plans,
# the catalog and the customers. No resources, no provider calls: it is a pure function of the repo.

variable "repo_root" {
  description = "Path to the repository root (the directory holding inventory/, customers/, products/)."
  type        = string
}

locals {
  root     = var.repo_root
  platform = yamldecode(file("${local.root}/inventory/platform.yaml"))
  regions  = { for r in yamldecode(file("${local.root}/inventory/regions.yaml")).regions : r.name => r }
  active   = { for k, r in local.regions : k => r if r.status == "active" }

  inventory_clusters = {
    for f in fileset("${local.root}/inventory/clusters", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.root}/inventory/clusters/${f}"))
  }
  inventory_sql = {
    for f in fileset("${local.root}/inventory/sql", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.root}/inventory/sql/${f}"))
  }

  projects        = { for k, p in local.platform.projects : k => p.id }
  project_numbers = { for k, p in local.platform.projects : k => p.number }

  products = {
    for f in fileset("${local.root}/products", "*/product.yaml") :
    dirname(f) => yamldecode(file("${local.root}/products/${f}")) if !startswith(f, "_")
  }
  customers = {
    for f in fileset("${local.root}/customers", "*/customer.yaml") :
    dirname(f) => yamldecode(file("${local.root}/customers/${f}")) if !startswith(f, "_")
  }
  customer_products = {
    for c in keys(local.customers) :
    c => try(yamldecode(file("${local.root}/customers/${c}/products.yaml")).spec.products, {})
  }
  data_sharing = {
    for c in keys(local.customers) :
    c => try(yamldecode(file("${local.root}/customers/${c}/data-sharing.yaml")).spec, {})
  }

  group_side = { devstage = "nonprod", uat = "nonprod", prod = "prod" }
  envs = {
    dev   = { group = "devstage", side = "nonprod" }
    stage = { group = "devstage", side = "nonprod" }
    uat   = { group = "uat", side = "nonprod" }
    prod  = { group = "prod", side = "prod" }
  }

  # IP plan per region per side (architecture §3).
  ip_plan = {
    for k, r in local.regions : k => {
      for side in ["nonprod", "prod"] : side => {
        cidr     = r.cidr[side]
        pod_cidr = r.podCidr[side]
        run      = cidrsubnet(r.cidr[side], 4, 2)  # x.x.32.0/20
        mig      = cidrsubnet(r.cidr[side], 6, 12) # x.x.48.0/22
        proxy    = cidrsubnet(r.cidr[side], 7, 26) # x.x.52.0/23
        ops      = cidrsubnet(r.cidr[side], 8, 54) # x.x.54.0/24
        psa      = cidrsubnet(r.cidr[side], 2, 1)  # x.x.64.0/18
      }
    }
  }

  # Every cluster declared by regions.yaml: cells, dedicated DR clusters and management clusters.
  cluster_list = concat(
    flatten([for rn, r in local.active : [
      for g in ["devstage", "uat", "prod"] : [
        for c in try(r.cells[g], []) : {
          name      = "${g}-${rn}-${c.id}"
          cell      = "${g}-${rn}-${c.id}"
          group     = g
          region    = rn
          side      = local.group_side[g]
          slot      = c.slot
          role      = "primary"
          capacity  = try(c.capacity.maxCustomers, local.platform.capacityDefaults[g])
          dr_active = try(c.drActive, false)
        }
      ]
    ]]),
    flatten([for rn, r in local.active : [
      for c in try(r.cells.prod, []) : {
        name      = "prod-${rn}-${c.id}-dr"
        cell      = "prod-${rn}-${c.id}"
        group     = "prod"
        region    = r.drPair
        side      = "prod"
        slot      = c.drSlot
        role      = "dr"
        capacity  = try(c.capacity.maxCustomers, local.platform.capacityDefaults.prod)
        dr_active = try(c.drActive, false)
      }
    ]]),
    [for side in ["nonprod", "prod"] : {
      name      = "mgmt-${side}"
      cell      = "mgmt-${side}"
      group     = "platform"
      region    = local.platform.hubRegion
      side      = side
      slot      = 0
      role      = "management"
      capacity  = 0
      dr_active = false
    }]
  )

  cluster_plan = {
    for c in local.cluster_list : c.name => merge(c, {
      zones         = local.regions[c.region].zones
      nodes_cidr    = cidrsubnet(local.regions[c.region].cidr[c.side], 8, c.slot)
      pods_cidr     = cidrsubnet(local.regions[c.region].podCidr[c.side], 5, c.slot)
      services_cidr = cidrsubnet(cidrsubnet(local.regions[c.region].podCidr[c.side], 2, 3), 7, c.slot)
      project_key   = c.group == "platform" ? "platform-${c.side}" : local.platform.groups[c.group].computeProject
    })
  }

  slot_keys = [for c in local.cluster_list : "${c.region}/${c.side}/${c.slot}"]

  sql_plan = merge(
    { for x in flatten([for rn, r in local.active : [
      for i in try(r.sqlInstances.nonprod, []) : {
        name     = "sql-nonprod-${rn}-${i.id}"
        side     = "nonprod"
        region   = rn
        cell     = null
        capacity = try(i.capacity.maxCustomers, local.platform.capacityDefaults.sqlNonprod)
        dr       = null
      }
    ]]) : x.name => x },
    { for x in flatten([for rn, r in local.active : [
      for c in try(r.cells.prod, []) : {
        name     = "sql-prod-${rn}-${c.id}"
        side     = "prod"
        region   = rn
        cell     = "prod-${rn}-${c.id}"
        capacity = local.platform.capacityDefaults.sqlProd
        dr       = { name = "sql-prod-${rn}-${c.id}-dr", region = r.drPair }
      }
    ]]) : x.name => x },
  )
}

output "platform" {
  value = local.platform
}

output "projects" {
  description = "Project key (e.g. compute-prod) => project ID."
  value       = local.projects
}

output "project_numbers" {
  value = local.project_numbers
}

output "regions" {
  value = local.regions
}

output "active_regions" {
  value = local.active

  precondition {
    condition     = alltrue([for k, r in local.active : try(local.regions[r.drPair].status, "") == "active"])
    error_message = "A prod region cannot be active without an active DR pair."
  }
}

output "ip_plan" {
  value = local.ip_plan
}

output "cluster_plan" {
  description = "Cluster name => plan (group, region, side, slot, role, ranges, project key)."
  value       = local.cluster_plan

  precondition {
    condition     = length(distinct(local.slot_keys)) == length(local.slot_keys)
    error_message = "Two clusters use the same slot in the same region and side (regions.yaml)."
  }
  precondition {
    condition     = alltrue([for c in local.cluster_list : c.slot >= 0 && c.slot <= 23])
    error_message = "Cluster slots must be between 0 and 23."
  }
}

output "sql_plan" {
  value = local.sql_plan
}

output "inventory_clusters" {
  description = "inventory/clusters/*.yaml as written by L2 (read by L3 and the edge)."
  value       = local.inventory_clusters
}

output "inventory_sql" {
  value = local.inventory_sql
}

output "products" {
  value = local.products
}

output "customers" {
  value = local.customers
}

output "customer_products" {
  value = local.customer_products
}

output "data_sharing" {
  value = local.data_sharing
}

output "envs" {
  value = local.envs
}
