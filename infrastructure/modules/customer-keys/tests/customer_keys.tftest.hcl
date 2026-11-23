mock_provider "google" {}

variables {
  repo_root = "../../.."
  customer  = "acme-corp"
}

run "nonprod_has_devstage_and_uat_rings_in_region" {
  command = plan

  variables {
    side = "nonprod"
  }

  assert {
    condition     = keys(module.key_ring) == ["devstage", "uat"]
    error_message = "one key ring per environment group"
  }
  assert {
    condition     = keys(module.key_ring["devstage"].key_ids) == ["us-east1/dev-app", "us-east1/dev-data", "us-east1/stage-app", "us-east1/stage-data"]
    error_message = "dev and stage keys in the customer's region"
  }
}

run "prod_ring_spans_region_pair_and_multiregion" {
  command = plan

  variables {
    side = "prod"
  }

  assert {
    condition     = toset(keys(module.key_ring["prod"].key_ids)) == toset(["us-east1/prod-data", "us-east1/prod-app", "us-central1/prod-data", "us-central1/prod-app", "us/prod-data", "us/prod-app"])
    error_message = "prod keys in us-east1, us-central1 and the us multi-region (dual-region buckets)"
  }
}
