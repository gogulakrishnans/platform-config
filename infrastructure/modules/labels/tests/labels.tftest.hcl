run "defaults_are_platform_shared" {
  command = plan

  assert {
    condition = output.labels == {
      customer      = "shared"
      environment   = "shared"
      "env-group"   = "shared"
      product       = "platform"
      "region-role" = "primary"
      "managed-by"  = "terraform"
    }
    error_message = "default labels must mark a shared platform resource"
  }
}

run "extra_cannot_override_mandatory" {
  command = plan

  variables {
    customer    = "acme-corp"
    environment = "prod"
    env_group   = "prod"
    product     = "payment"
    extra       = { customer = "evil", team = "payments" }
  }

  assert {
    condition     = output.labels.customer == "acme-corp" && output.labels.team == "payments"
    error_message = "mandatory keys must win over extra labels"
  }
}

run "rejects_invalid_environment" {
  command = plan

  variables {
    environment = "qa"
  }

  expect_failures = [var.environment]
}

run "rejects_long_customer_id" {
  command = plan

  variables {
    customer = "a-customer-id-that-is-too-long"
  }

  expect_failures = [var.customer]
}
