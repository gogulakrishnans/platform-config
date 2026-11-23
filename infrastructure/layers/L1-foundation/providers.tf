terraform {
  required_version = ">= 1.7.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 8.0, < 9.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 3.0, < 4.0"
    }
  }

  # Partial GCS backend: bucket from backend.hcl, prefix "L1/foundation" (see infrastructure/README.md).
  backend "gcs" {}
}

# Credentials come from the runner's keyless identity (WIF on GitHub-hosted runners for the first
# apply, Workload Identity on the prod pool afterwards). No key files.
provider "google" {}

# Management clusters are reached through their DNS-based endpoints with an IAM access token.
provider "helm" {
  alias = "nonprod"
  kubernetes = {
    host  = "https://${module.platform["nonprod"].mgmt_cluster.endpoint}"
    token = data.google_client_config.this.access_token
  }
}

provider "helm" {
  alias = "prod"
  kubernetes = {
    host  = "https://${module.platform["prod"].mgmt_cluster.endpoint}"
    token = data.google_client_config.this.access_token
  }
}
