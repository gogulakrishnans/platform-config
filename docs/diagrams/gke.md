# GKE deployment architecture (D2)

Exported SVG: [gke.svg](gke.svg). It shows one region (`us-east1`) with its DR pair (`us-central1`) and the two example customers. Other regions repeat the same pattern.

```mermaid
flowchart TB
  user(["Customer users<br/>(internet)"])
  ops(["Operators<br/>(IAP)"])
  saas(["Allowlisted<br/>external APIs"])

  subgraph git["Git: platform-config"]
    cfg["customers/*/customer.yaml (placement)<br/>customers/*/products.yaml (version pins)"]
    charts["helm/tenant · helm/product-base<br/>values: base → product → env → customer"]
  end

  subgraph pnp["platform-nonprod · non-prod perimeter"]
    argoNP["ArgoCD Dev/Stage + ArgoCD UAT<br/>(management cluster)"]
    arNP[("Artifact Registry non-prod<br/>build target, signed: non-prod attestor")]
  end

  subgraph pprod["platform-prod · prod perimeter"]
    argoP["ArgoCD Prod<br/>(management cluster)<br/>ApplicationSets: create/update only"]
    arP[("Artifact Registry prod (multi-region)<br/>promoted by digest + prod attestation")]
  end

  arNP -- "promotion job (prod pool)<br/>copy by digest" --> arP

  subgraph devstage["compute-devstage · devstage-us-east1-01 · RAPID · private only"]
    ilb["Regional internal ALB<br/>*.dev|stage.platform.internal (CAS cert)"]
    igwDS["Istio ingress gateway"]
    subgraph nsDS["Namespaces from tenant chart"]
      nsDev["acme-corp-dev"]
      nsStg["acme-corp-stage"]
      nsBDev["beta-industries-dev · -stage"]
    end
  end

  subgraph uat["compute-uat · uat-us-east1-01 · REGULAR"]
    armorU["Cloud Armor<br/>IP allowlist"] --> glbU["Global external ALB<br/>*.uat.platform.example"]
    glbU --> igwU["Istio ingress gateway"]
    igwU --> nsUat["acme-corp-uat · beta-industries-uat"]
  end

  subgraph prod["compute-prod · prod-us-east1-01 · STABLE · regional, 3 zones"]
    igwP["Istio ingress gateway<br/>RequestAuthentication (JWT)<br/>AuthorizationPolicy: customer claim = host"]
    subgraph nsA["ns acme-corp-prod (tenant chart)"]
      podA["payment-api Rollout (canary)<br/>KSA payment · PDB · HPA<br/>Istio sidecar, mTLS STRICT"]
      polA["default-deny NetworkPolicy · Sidecar scope<br/>ResourceQuota · LimitRange · StorageClass sc-acme-corp-prod"]
    end
    subgraph nsB["ns beta-industries-prod"]
      podB["product pods (own KSA, own policies)"]
    end
    egw["Istio egress gateway<br/>ServiceEntry allowlist"]
  end

  subgraph edge["compute-prod · global edge"]
    armorP["Cloud Armor<br/>WAF · DDoS · bot · rate limit per IP + per customer"]
    glbP["Global external ALB + Cloud CDN<br/>Certificate Manager map<br/>acme-corp.platform.example · *.acme-corp…"]
  end

  subgraph dr["compute-prod · prod-us-east1-01-dr (us-central1) · DR"]
    drNs["acme-corp-prod · beta-industries-prod<br/>same Applications at minimum replicas<br/>scaled up on failover"]
  end

  subgraph data["data-prod (customer containers)"]
    sql[("sql-prod-us-east1-01 · Enterprise Plus HA<br/>db acme_corp_prod → schema payment<br/>write endpoint")]
    sqlDr[("sql-prod-us-east1-01-dr<br/>cross-region DR replica")]
    gcs[("pfx-acme-corp-payment-prod<br/>dual-region + turbo, CMEK")]
  end

  subgraph sec["security-prod"]
    kms["kr-acme-corp-prod<br/>keys in us-east1, us-central1, us"]
  end

  nat["Cloud NAT<br/>static egress IPs"]

  %% ingress paths
  ops -- "IAP" --> ilb --> igwDS --> nsDS
  user --> armorU
  user --> armorP --> glbP -- "NEG (primary)" --> igwP --> podA
  glbP -. "failover: NEG (DR)" .-> drNs

  %% delivery
  cfg --> argoNP
  cfg --> argoP
  charts --> argoNP
  charts --> argoP
  argoNP -- "DNS-based control-plane endpoint<br/>IAM + WI auth, no stored creds" --> devstage
  argoNP --> uat
  argoP -- "tenant + product ApplicationSets" --> prod
  argoP -- "prod ApplicationSet target 2: DR" --> dr
  arP -- "pull (Binary Authorization: prod attestation)" --> prod
  arP --> dr
  arNP --> devstage
  arNP --> uat

  %% identity and data
  podA -- "WIF: KSA principal → bucket IAM" --> gcs
  podA -- "Auth Proxy, impersonate GSA acme-corp-prod<br/>IAM DB login, CONNECT only own DB" --> sql
  sql -- "async replication" --> sqlDr
  gcs -. "CMEK" .- kms
  sql -. "platform key + app envelope (customer key)" .- kms

  %% egress
  podA --> egw --> nat --> saas

  classDef prodC fill:#fde7e7,stroke:#c62828,color:#000
  classDef nonprodC fill:#e8f1fd,stroke:#1565c0,color:#000
  classDef drC fill:#fff4e0,stroke:#ef6c00,color:#000
  classDef dataC fill:#e9f7ef,stroke:#2e7d32,color:#000
  class prod,edge,pprod prodC
  class devstage,uat,pnp nonprodC
  class dr drC
  class data,sec dataC
```

## What the diagram shows

| Aspect | Where |
|---|---|
| Topology | Three environment groups, each with its own cluster and exposure. The management clusters host the ArgoCD instances. |
| Tenant isolation | One namespace per customer per env from the tenant chart: default-deny NetworkPolicy, Istio Sidecar scoping and AuthorizationPolicy, quotas, a per-customer StorageClass and AppProject. Data isolation comes from per-customer containers (database, bucket) and identities. |
| Ingress | Dev/Stage: IAP → internal ALB. UAT: Cloud Armor allowlist → global ALB. Prod: Cloud Armor → global ALB + CDN → Istio ingress gateway (JWT checked). |
| Egress | Istio egress gateway with a ServiceEntry allowlist, NetworkPolicy + firewall default deny, Cloud NAT static IPs. |
| Identity | KSA principal via WIF for GCS/BQ/PubSub/KMS/Secret Manager. Pods impersonate the customer env GSA for Cloud SQL IAM login. |
| Deploy path | Git → ArgoCD (per group) → private cluster endpoints. Images are built into the non-prod AR and promoted by digest into the prod AR. Binary Authorization requires the prod attestation. |
| DR copy | Dedicated `prod-us-east1-01-dr` in `us-central1` receives every prod Application at minimum replicas. The Cloud SQL DR replica sits in the same pair region, and the LB fails over to the DR NEG. |
