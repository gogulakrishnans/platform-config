# Data architecture (Mermaid, backup)

Backup of the Mermaid version. The current diagram is the Google Cloud icon version on [../data.md](../data.md).

Shared instances, per-customer containers. See [architecture §8](../../architecture.md#8-data-architecture).

```mermaid
flowchart TB
  subgraph nonprod["data-nonprod · us-east1"]
    sqlnp[("sql-nonprod-us-east1-01 (≤ 40 customers)")]
    sqlnp --> d1["acme_corp_dev<br/>schemas: payment, reporting"]
    sqlnp --> d2["acme_corp_stage"]
    sqlnp --> d3["acme_corp_uat"]
    sqlnp --> d4["beta_industries_dev / _stage / _uat"]
    gnp["Buckets: pfx-acme-corp-{product}-{dev|stage|uat}<br/>regional · CMEK kr-acme-corp-devstage / -uat"]
    bnp["Datasets: acme_corp_{product}_{env}"]
    tnp["Topics: acme-corp-{product}-{env}-{name}"]
  end

  subgraph prod["data-prod · us-east1 (primary)"]
    sqlp[("sql-prod-us-east1-01<br/>Enterprise Plus · regional HA (≤ 25 customers)")]
    sqlp --> p1["acme_corp_prod<br/>schemas: payment, reporting<br/>CONNECT: acme-corp-prod login only"]
    sqlp --> p2["other customers' prod DBs on this cell"]
    gp["pfx-acme-corp-{product}-prod<br/>dual-region us-east1+us-central1, turbo<br/>CMEK key ring location: us"]
    bp["acme_corp_{product}_prod (us-east1)"]
    tp["acme-corp-{product}-prod-*<br/>storage: us-east1, us-central1"]
  end

  subgraph prodDr["data-prod · us-central1 (DR pair)"]
    sqlr[("sql-prod-us-east1-01-dr<br/>cross-region DR replica, same size")]
    bdr["acme_corp_{product}_prod_dr<br/>daily cross-region copy (RPO 24 h)"]
  end

  subgraph ex["data-exchange"]
    xs["pfx-acme-corp-shared + acme_corp_shared<br/>shared reference (read by all 4 envs)"]
    xd["pfx-acme-corp-seed<br/>sanitized dumps (7-day lifecycle)"]
  end

  sqlp -- "async, write endpoint follows primary" --> sqlr
  bp -- "DTS cross_region_copy daily" --> bdr

  boot{{"DB bootstrap job (Cloud Run job per side)<br/>REVOKE CONNECT/TEMP FROM PUBLIC<br/>GRANT CONNECT to env login<br/>CREATE SCHEMA per product<br/>write _platform_bootstrap marker"}}
  boot --> sqlnp
  boot --> sqlp
```

| Store | Unit per customer | Isolation | Prod DR |
|---|---|---|---|
| Cloud SQL | database per env, schema per product | `CONNECT` per env login | DR replica, RPO ~5 min |
| GCS | bucket per product per env | bucket IAM + CMEK | dual-region turbo, RPO ≤ 15 min |
| BigQuery | dataset per product per env | dataset IAM + CMEK | daily copy, RPO 24 h |
| Pub/Sub | topics per product per env | topic/sub IAM + CMEK | storage in region + pair |
| PVC (exception) | PVC in customer namespace | namespace + per-customer StorageClass/CMEK | Backup for GKE in pair |
