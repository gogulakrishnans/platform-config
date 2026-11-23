# Cloud Run deployment architecture (D2) (Mermaid, backup)

Backup of the Mermaid version. The current diagram is the Google Cloud icon version on [../cloud-run.md](../cloud-run.md).

Exported SVG: [cloud-run.svg](cloud-run.svg). Example: `acme-corp` runs `reporting-engine` (Cloud Run), which subscribes to events published by `payment-api` (GKE). The customer's region is `us-east1` and its DR pair is `us-central1`.

```mermaid
flowchart TB
  user(["Customer users<br/>(internet)"])
  ops(["Operators<br/>(IAP)"])

  subgraph git["Git: platform-config"]
    pins["customers/acme-corp/products.yaml<br/>reporting-engine: { dev: 1.9.0, …, prod: 1.8.2 }"]
  end

  subgraph runner["platform-prod · GitHub Actions prod pool (ephemeral, WIF)"]
    deploy["Cloud Run deploy step<br/>1. run migration job<br/>2. deploy revision --no-traffic --tag<br/>3. traffic 10 → 25 → 50 → 100<br/>4. SLO check, auto-rollback"]
  end
  arP[("Artifact Registry prod<br/>image by digest")]

  subgraph np["Non-prod (compute-devstage / compute-uat)"]
    ilb["Dev/Stage: regional internal ALB<br/>serverless NEG · IAP"]
    runDev["acme-corp-reporting-dev<br/>acme-corp-reporting-stage"]
    glbU["UAT: Cloud Armor allowlist → global ALB<br/>serverless NEG"]
    runUat["acme-corp-reporting-uat"]
  end

  subgraph edge["compute-prod · global edge"]
    armor["Cloud Armor<br/>WAF · rate limit per customer host"]
    glb["Global external ALB<br/>host rule acme-corp.platform.example<br/>path /v1/reports → backend service"]
    negP["Serverless NEG us-east1"]
    negD["Serverless NEG us-central1 (DR)"]
  end

  subgraph prodP["compute-prod · us-east1 (primary)"]
    subgraph svc["Service acme-corp-reporting-prod"]
      rev1["revision 1.8.2<br/>traffic 90%"]
      rev2["revision 1.8.3 (tag canary)<br/>traffic 10%"]
    end
    job["Cloud Run job<br/>acme-corp-reporting-prod-migrate"]
    idn["Runs as GSA acme-corp-prod<br/>ingress: internal-and-cloud-load-balancing<br/>invoker: LB + Pub/Sub push SA only<br/>Direct VPC egress (all traffic), tag t-acme-corp-prod<br/>min instances ≥ 1"]
  end

  subgraph prodD["compute-prod · us-central1 (DR copy)"]
    svcD["Service acme-corp-reporting-prod<br/>same image digest, min instances 0-1<br/>scaled on failover"]
  end

  subgraph gke["compute-prod · GKE prod-us-east1-01"]
    pay["payment-api (acme-corp-prod)<br/>publisher"]
  end

  subgraph data["data-prod"]
    topic[["Topic acme-corp-payment-prod-events<br/>storage: us-east1, us-central1 · CMEK"]]
    sub[["Push subscription → reporting<br/>OIDC token (push SA) · retry policy"]]
    dlq[["Dead-letter topic<br/>acme-corp-payment-prod-events-dlq"]]
    sql[("sql-prod-us-east1-01<br/>db acme_corp_prod → schema reporting<br/>write endpoint")]
    bq[("BigQuery acme_corp_reporting_prod<br/>daily copy → us-central1")]
    gcs[("pfx-acme-corp-reporting-prod<br/>dual-region + turbo")]
  end

  nat["Cloud NAT"]

  pins --> deploy
  arP --> deploy
  deploy -- "Binary Authorization: prod attestation" --> svc
  deploy --> job
  deploy --> svcD

  user --> armor --> glb
  glb --> negP --> svc
  glb -. "failover / health" .-> negD -.-> svcD
  ops --> ilb --> runDev
  user -. "allowlisted testers" .-> glbU --> runUat

  pay -- "publish (KSA via WIF)" --> topic
  topic --> sub -- "OIDC-authenticated push / Eventarc<br/>(internal-only service)" --> svc
  sub -- "max delivery attempts" --> dlq
  sub -. "re-pointed on failover" .-> svcD

  svc -- "Cloud SQL connector, IAM login acme-corp-prod" --> sql
  job -- "migrate schema reporting (expand/contract)" --> sql
  svc --> bq
  svc --> gcs
  svc -- "egress via firewall" --> nat

  classDef prodC fill:#fde7e7,stroke:#c62828,color:#000
  classDef nonprodC fill:#e8f1fd,stroke:#1565c0,color:#000
  classDef drC fill:#fff4e0,stroke:#ef6c00,color:#000
  classDef dataC fill:#e9f7ef,stroke:#2e7d32,color:#000
  class prodP,edge,runner,gke prodC
  class np nonprodC
  class prodD drC
  class data dataC
```

## What the diagram shows

| Aspect | Where |
|---|---|
| Topology | One service per customer × product × env, in the env group's compute project and the customer's region. Prod has a second copy in the pair region. |
| Tenant isolation | Separate service per customer, running as the customer env GSA, which can only reach that customer's database (`CONNECT`), bucket, dataset and topics. Invoker IAM allows only the LB and the customer's push SA. A per-tenant network tag drives the firewall. |
| Ingress | Prod: Cloud Armor → global ALB → serverless NEG; ingress is restricted to `internal-and-cloud-load-balancing`. Dev/Stage: internal ALB with IAP. UAT: allowlisted global ALB. |
| Egress | Direct VPC egress for all traffic → VPC firewall → Cloud NAT. |
| Events | GKE `payment-api` publishes. The Cloud Run service subscribes through an OIDC-authenticated push (or Eventarc), with a dead-letter topic and retry. Consumers are idempotent. |
| Deploy path | Version pin in Git → prod runner pool deploy step: migration job, then a no-traffic revision, then a staged traffic split with automatic rollback. Terraform (L3) owns the service shape and ignores the revision. |
| DR copy | Same digest deployed in `us-central1` behind a second serverless NEG on the same backend service. Push subscriptions are re-pointed on failover. |
