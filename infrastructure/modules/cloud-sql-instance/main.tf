# Pooled Cloud SQL for PostgreSQL instance (architecture §8). Prod: Enterprise Plus, regional HA,
# cross-region DR replica designated for advanced DR with a PSA write endpoint (verification V9).
# The database bootstrap job logs in as an IAM user holding cloudsqlsuperuser (verification V10).

locals {
  dr_name = var.dr == null ? null : "${var.name}-dr"
  flags = merge({
    "cloudsql.iam_authentication" = "on"
    "log_connections"             = "on"
    "log_disconnections"          = "on"
    "cloudsql.enable_pgaudit"     = "on"
  }, var.extra_flags)
}

resource "google_sql_database_instance" "primary" {
  project             = var.project_id
  name                = var.name
  region              = var.region
  database_version    = var.database_version
  encryption_key_name = var.encryption_key
  deletion_protection = var.deletion_policy == "PREVENT"
  deletion_policy     = var.deletion_policy

  settings {
    tier                        = var.tier
    edition                     = var.edition
    availability_type           = "REGIONAL"
    disk_autoresize             = true
    disk_type                   = "PD_SSD"
    user_labels                 = var.labels
    deletion_protection_enabled = var.deletion_policy == "PREVENT"

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.network_id
      allocated_ip_range                            = var.psa_range_name
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      start_time                     = "03:00"

      backup_retention_settings {
        retained_backups = 30
      }
    }

    dynamic "database_flags" {
      for_each = local.flags
      content {
        name  = database_flags.key
        value = database_flags.value
      }
    }

    insights_config {
      query_insights_enabled = true
    }

    maintenance_window {
      day          = 7
      hour         = 4
      update_track = var.maintenance_track
    }

    dynamic "data_cache_config" {
      for_each = var.edition == "ENTERPRISE_PLUS" ? [1] : []
      content {
        data_cache_enabled = true
      }
    }
  }

  # Advanced DR: designate the cross-region replica once it exists (second apply on first build,
  # documented in the L2 runbook). The write endpoint follows the primary on switchover/failover.
  dynamic "replication_cluster" {
    for_each = var.dr != null && var.designate_dr_replica ? [1] : []
    content {
      failover_dr_replica_name = "${var.project_id}:${local.dr_name}"
      psa_write_endpoint       = true
    }
  }
}

resource "google_sql_database_instance" "dr" {
  count = var.dr == null ? 0 : 1

  project              = var.project_id
  name                 = local.dr_name
  region               = var.dr.region
  database_version     = var.database_version
  master_instance_name = google_sql_database_instance.primary.name
  encryption_key_name  = var.dr.encryption_key
  deletion_protection  = var.deletion_policy == "PREVENT"
  deletion_policy      = var.deletion_policy

  settings {
    tier              = var.tier # same size as the primary so it can take the load
    edition           = var.edition
    availability_type = "REGIONAL"
    disk_autoresize   = true
    disk_type         = "PD_SSD"
    user_labels       = merge(var.labels, { "region-role" = "dr" })

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.network_id
      allocated_ip_range                            = var.dr.psa_range_name
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    dynamic "database_flags" {
      for_each = local.flags
      content {
        name  = database_flags.key
        value = database_flags.value
      }
    }
  }
}

resource "google_sql_user" "bootstrap" {
  count = var.bootstrap_service_account == null ? 0 : 1

  project        = var.project_id
  instance       = google_sql_database_instance.primary.name
  name           = trimsuffix(var.bootstrap_service_account, ".gserviceaccount.com")
  type           = "CLOUD_IAM_SERVICE_ACCOUNT"
  database_roles = ["cloudsqlsuperuser"]
}
