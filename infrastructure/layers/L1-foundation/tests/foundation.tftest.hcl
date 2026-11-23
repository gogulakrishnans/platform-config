mock_provider "google" {}
mock_provider "helm" {
  alias = "nonprod"
}

mock_provider "helm" {
  alias = "prod"
}

run "fixed_project_set_and_perimeters" {
  command = plan

  assert {
    condition     = length(module.project) == 12
    error_message = "the project count is fixed at 12 regardless of customers"
  }
  assert {
    condition     = module.project["net-prod"].project_id == "pfx-net-prod"
    error_message = "project IDs come from inventory/platform.yaml"
  }
  assert {
    condition     = toset(keys(module.vpc_sc.perimeters)) == toset(["nonprod", "prod", "exchange"])
    error_message = "three VPC-SC perimeters"
  }
  assert {
    condition     = length(helm_release.argocd_nonprod) == 2
    error_message = "Dev/Stage and UAT ArgoCD instances on the non-prod management cluster; prod has its own"
  }
}
