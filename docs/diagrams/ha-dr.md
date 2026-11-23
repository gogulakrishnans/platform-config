# HA and DR (per prod cell)

> **Google Cloud icon version:** [ha-dr-gcp.svg](ha-dr-gcp.svg) (zoomable) · [ha-dr-gcp.png](ha-dr-gcp.png) · source [src/ha_dr.py](src/ha_dr.py). The Mermaid diagram below has the same content.

Warm standby in the DR pair by default. Failover is per cell. See [architecture §12](../architecture.md#12-ha-and-dr).

```mermaid
flowchart LR
  users(["Users"]) --> glb["Global external ALB<br/>health checks per backend"]

  subgraph primary["us-east1 · prod cell prod-us-east1-01"]
    gke["GKE regional (3 zones)<br/>PDBs · topology spread"]
    run["Cloud Run services (multi-zone)"]
    mig["Regional MIGs (3 zones, autohealing)"]
    sql[("sql-prod-us-east1-01<br/>Enterprise Plus · regional HA")]
  end

  subgraph dr["us-central1 · DR for this cell"]
    gkeDr["prod-us-east1-01-dr<br/>min replicas (full size if hot-standby)"]
    runDr["Cloud Run copies (min instances 0-1)"]
    migDr["MIGs at minimum size"]
    sqlDr[("sql-prod-us-east1-01-dr<br/>DR replica, same size")]
  end

  subgraph both["Spans both regions"]
    gcs[("GCS dual-region + turbo (RPO ≤ 15 min)")]
    ps[["Pub/Sub (storage: region + pair)"]]
    kms["KMS keys in both regions + us"]
    ar[("AR prod multi-region")]
    sec["Secrets replicated"]
  end

  bq[("BigQuery us-east1")] -- "daily copy (RPO 24 h)" --> bqDr[("BigQuery us-central1")]
  bk["Backup for GKE (PVCs) stored in us-central1"]

  glb --> gke & run & mig
  glb -. "failover" .-> gkeDr & runDr & migDr
  sql -- "async replication (RPO ~5 min)" --> sqlDr
  gke & run & mig --> sql
  gkeDr & runDr & migDr -. "after promote, via write endpoint" .-> sqlDr
  gke --> bk

  rb{{"Failover runbook (RTO ~30 min)<br/>1 freeze deploys to cell<br/>2 promote-replica --failover<br/>3 confirm write endpoint<br/>4 scale DR cluster / MIGs / Cloud Run<br/>5 shift LB backends<br/>6 re-point push subscriptions<br/>7 verify SLOs · failback = switchover"}}
```

| Profile | RTO | RPO |
|---|---|---|
| Zone failure | ~1-5 min | 0 |
| Region failure, warm standby (default) | ~30 min | ~5 min |
| Region failure, hot standby (opt-in) | ~5 min | ~1 min |
| Non-prod | 4 h | 24 h |
