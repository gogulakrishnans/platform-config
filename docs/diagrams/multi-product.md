# Multi-product composition

How the catalog and a customer's selection become infrastructure and workloads. See [architecture §6](../architecture.md#6-multi-product-and-multi-customer-model).

```mermaid
flowchart LR
  subgraph cat["Catalog (platform-owned)"]
    p1["payment-api<br/>runtime: gke · sql · bucket · publish events"]
    p2["reporting-engine<br/>runtime: cloud-run · sql · bucket · bq · subscribe payment-events<br/>depends on payment-api"]
    p3["legacy-billing<br/>runtime: mig · sql · bucket"]
  end

  subgraph sel["customers/acme-corp/products.yaml"]
    s1["payment-api: dev 2.6.0-beta.1 … prod 2.5.0"]
    s2["reporting-engine: dev 1.9.0 … prod 1.8.2"]
  end

  val{{"PR validator<br/>dependencies · runtime rules (subscribe = cloud-run only,<br/>PVC = approved GKE only) · version window ·<br/>name lengths · plan summary comment"}}
  cat --> val
  sel --> val

  val --> l3["L3 composition module (per env)<br/>merge: largest size wins · union resources · overrides last"]
  val --> l4["L4 delivery"]

  subgraph out3["Created by L3 for acme-corp prod"]
    db["acme_corp_prod → schemas payment, reporting"]
    b["pfx-acme-corp-payment-prod · pfx-acme-corp-reporting-prod"]
    d["acme_corp_reporting_prod (+ _dr)"]
    t["acme-corp-payment-prod-events · push sub → reporting · DLQ"]
    crs["Cloud Run service acme-corp-reporting-prod (shape)"]
    id["GSA acme-corp-prod · IAM per resource · keys"]
  end

  subgraph out4["Delivered by L4"]
    ns["Tenant chart: ns acme-corp-prod (+ DR cluster)"]
    rel["Helm release payment-api 2.5.0 (Rollout)"]
    rev["Cloud Run revision 1.8.2 (traffic split)"]
  end

  l3 --> db & b & d & t & crs & id
  l4 --> ns & rel & rev
```

**Day 2**
- **Add:** a PR to `products.yaml`. L3 adds only the new product's resources, then bootstrap creates the schema and L4 deploys it.
- **Remove:** phased decommission with a retention period and two approvals. Other products are untouched.
- **Upgrade:** version pin PRs in rollout waves.
