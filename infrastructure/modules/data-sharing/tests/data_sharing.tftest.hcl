mock_provider "google" {}

variables {
  repo_root = "../../.."
}

run "acme_corp_shares_reference_and_seeds_down" {
  command = plan

  variables {
    customer = "acme-corp"
  }

  assert {
    condition     = module.shared_bucket.name == "pfx-acme-corp-shared" && module.shared_dataset.dataset_id == "acme_corp_shared"
    error_message = "one shared bucket and dataset per customer in data-exchange"
  }
  assert {
    condition     = output.seed_bucket == "pfx-acme-corp-seed"
    error_message = "seed bucket exists because seedDown.targets is not empty"
  }
  assert {
    condition     = length(output.readers) == 8
    error_message = "all four environment identities (GSA + namespace principal set) of this customer read shared reference"
  }
  assert {
    condition     = alltrue([for r in output.readers : strcontains(r, "acme-corp-")])
    error_message = "only this customer's identities are granted"
  }
}

run "beta_industries_has_no_seed_bucket" {
  command = plan

  variables {
    customer = "beta-industries"
  }

  assert {
    condition     = output.seed_bucket == null
    error_message = "seedDown.targets is empty"
  }
}
