# Golden image for the legacy-billing MIG product (architecture §5, Instance Group diagram).
# Built on the non-prod pool into platform-nonprod (image family legacy-billing); promotion copies the
# image to platform-prod and records it in products/legacy-billing/releases.yaml. The org policy
# compute.trustedImageProjects allows only these two projects (C8).
#
#   packer init . && packer build -var-file=example.pkrvars.hcl -var version=3.4.1 .

packer {
  required_version = ">= 1.11.0"
  required_plugins {
    googlecompute = {
      source  = "github.com/hashicorp/googlecompute"
      version = "~> 1.2.9"
    }
    ansible = {
      source  = "github.com/hashicorp/ansible"
      version = "~> 1.1.6"
    }
  }
}

variable "project_id" {
  description = "platform-nonprod project (image build target)"
  type        = string
}

variable "region" {
  type    = string
  default = "us-east1"
}

variable "subnetwork" {
  description = "build subnet in the non-prod Shared VPC (no external IP, Cloud NAT for packages)"
  type        = string
}

variable "version" {
  description = "product release, e.g. 3.4.1"
  type        = string
  default     = "0.0.0"
  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.version))
    error_message = "The version must be semver (major.minor.patch)."
  }
}

variable "artifact_uri" {
  description = "gs:// path of the release bundle produced by the product pipeline"
  type        = string
}

variable "kms_key" {
  description = "platform CMEK key for image disks"
  type        = string
}

locals {
  image_name = "legacy-billing-${replace(var.version, ".", "-")}"
}

source "googlecompute" "legacy_billing" {
  project_id              = var.project_id
  zone                    = "${var.region}-b"
  subnetwork              = var.subnetwork
  omit_external_ip        = true
  use_internal_ip         = true
  use_iap                 = true
  source_image_family     = "debian-12"
  source_image_project_id = ["debian-cloud"]
  machine_type            = "e2-standard-2"
  disk_size               = 20
  image_name              = local.image_name
  image_family            = "legacy-billing"
  image_description       = "legacy-billing ${var.version} golden image"
  image_encryption_key {
    kmsKeyName = var.kms_key
  }
  image_storage_locations = [var.region]
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  ssh_username = "packer"
  tags         = ["packer-build"]
  image_labels = {
    customer      = "shared"
    environment   = "shared"
    "env-group"   = "shared"
    product       = "billing"
    "region-role" = "primary"
    "managed-by"  = "packer"
    version       = local.image_name
  }
}

build {
  sources = ["source.googlecompute.legacy_billing"]

  # Bake the OS hardening, the runtime and the release; per-customer configuration is applied at
  # boot from instance metadata and by the Ansible runners, never baked in.
  provisioner "ansible" {
    playbook_file = "${path.root}/../ansible/site.yml"
    user          = "packer"
    extra_arguments = [
      "--extra-vars", "phase=bake version=${var.version} artifact_uri=${var.artifact_uri}",
      "--scp-extra-args", "'-O'",
    ]
  }

  post-processor "manifest" {
    output = "packer-manifest.json"
  }
}
