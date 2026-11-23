# Instance Group (MIG) deployment architecture (D2)

Exported SVG: [instance-group.svg](instance-group.svg). Example: `beta-industries` runs `legacy-billing` (VM-based) in `us-central1`, with its DR pair in `us-east1`.

```mermaid
flowchart TB
  user(["Customer users<br/>(internet)"])

  subgraph git["Git"]
    pins["customers/beta-industries/products.yaml<br/>legacy-billing: { …, prod: 3.4.1 }"]
    pk["packer/ · ansible/ (playbooks, roles)"]
  end

  subgraph pnp["platform-nonprod · non-prod pool"]
    packer["Packer build (GitHub Actions)<br/>hardened base + app 3.4.1<br/>Shielded VM, signed"]
    imgNP[("Image family legacy-billing<br/>(trusted image project)")]
    ansNP["Ansible runners (non-prod)<br/>OS Login · IAP-only SSH · no public IP"]
  end

  subgraph pprod["platform-prod · prod pool"]
    promo["Promotion job<br/>copy image, verify + record attestation"]
    imgP[("Prod image family legacy-billing<br/>(trusted image project)")]
    roll["MIG deploy step<br/>new instance template → rolling update<br/>maxUnavailable 0 · maxSurge 3 · canary 10%"]
    ansP["Ansible runners (prod)<br/>dynamic inventory by labels<br/>customer=beta-industries, product=billing"]
  end

  subgraph edge["compute-prod · global edge"]
    armor["Cloud Armor<br/>WAF · rate limit per IP + per customer"]
    glb["Global external ALB<br/>host beta-industries.platform.example"]
    bes["Backend service beta-industries-billing-prod<br/>health check · connection draining · TLS to backend"]
  end

  subgraph prodP["compute-prod · us-central1 (primary)"]
    mig["Regional MIG beta-industries-billing-prod<br/>3 zones · autohealing · autoscaling<br/>template: prod image 3.4.1, Shielded VM, no external IP"]
    vmid["VM identity: GSA beta-industries-prod<br/>network tag t-beta-industries-prod<br/>labels: customer, product, environment…"]
    fw["VPC firewall (default deny)<br/>allow: GFE + health-check ranges → tag<br/>allow: Ansible tag → tag :22<br/>no tenant tag → other tenant tag"]
  end

  subgraph prodD["compute-prod · us-east1 (DR copy)"]
    migD["Regional MIG beta-industries-billing-prod (DR)<br/>same image, minimum size<br/>scaled up on failover"]
  end

  subgraph np["Non-prod (compute-devstage / compute-uat)"]
    migNP["beta-industries-billing-dev | -stage | -uat<br/>regional MIGs, non-prod image family"]
  end

  subgraph data["data-prod / data-exchange"]
    sql[("sql-prod-us-central1-01<br/>db beta_industries_prod → schema billing<br/>Auth Proxy on VM, IAM login")]
    gcs[("pfx-beta-industries-billing-prod<br/>dual-region + turbo")]
    shared[("pfx-beta-industries-shared<br/>gcsfuse read-only mount")]
  end

  nat["Cloud NAT"]

  pk --> packer --> imgNP
  imgNP -- "cross-perimeter read only<br/>(prod promoter identity)" --> promo --> imgP
  pins --> roll
  imgP --> roll
  roll --> mig
  roll --> migD
  imgNP --> migNP
  ansNP -- "config + migrations (private IP)" --> migNP
  ansP -- "1. migration task (expand/contract)<br/>2. configuration, private IP over SSH" --> mig

  user --> armor --> glb --> bes --> mig
  bes -. "failover backend" .-> migD

  mig --- vmid
  mig --- fw
  mig -- "IAM DB login beta-industries-prod" --> sql
  mig --> gcs
  mig --> shared
  mig -- "egress" --> nat

  classDef prodC fill:#fde7e7,stroke:#c62828,color:#000
  classDef nonprodC fill:#e8f1fd,stroke:#1565c0,color:#000
  classDef drC fill:#fff4e0,stroke:#ef6c00,color:#000
  classDef dataC fill:#e9f7ef,stroke:#2e7d32,color:#000
  class prodP,edge,pprod prodC
  class np,pnp nonprodC
  class prodD drC
  class data dataC
```

## What the diagram shows

| Aspect | Where |
|---|---|
| Topology | Stateless regional MIG per customer × product × env (3 zones, autohealing), in the env group's compute project. No data disks: code is in the Packer image, config comes from Ansible, data lives in Cloud SQL/GCS. |
| Tenant isolation | Separate MIG and instance template running as the customer env GSA. Per-tenant network tag with default-deny firewall: only LB/health-check ranges and the Ansible runners can reach a tenant's VMs, and no tenant tag can reach another. Data access is limited to that customer's containers. |
| Ingress | Cloud Armor → global ALB → backend service → regional MIG, with TLS to the backend and connection draining. |
| Egress | Firewall → Cloud NAT. |
| Identity | VM service account = customer env GSA; IAM DB login through the Cloud SQL Auth Proxy; OS Login for operators through IAP only. |
| Deploy path | Packer (non-prod pool) → non-prod image family → promotion (prod pool) → prod image family → new instance template → rolling update (`maxUnavailable=0`). Ansible runs migrations first, then configuration. Blue-green uses a second MIG on the same backend service. |
| DR copy | Same image in a MIG in the pair region at minimum size, attached as a failover backend and scaled up on failover. |
