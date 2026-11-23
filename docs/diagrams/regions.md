# Region model and placement

See [architecture §3](../architecture.md#3-regions-cells-and-placement).

```mermaid
flowchart LR
  subgraph gitIn["Git (read only by placement)"]
    reg["inventory/regions.yaml<br/>status · drPair · cidr · podCidr · quotas"]
    cl["inventory/clusters/*.yaml<br/>(written by L2)"]
    sq["inventory/sql/*.yaml<br/>(written by L2)"]
    cust["customers/*/customer.yaml<br/>region.primary (+ existing placement)"]
    prods["customers/*/products.yaml<br/>+ products/*/product.yaml"]
  end

  pr(["New customer PR<br/>region.primary: us-east1"]) --> job

  job{{"Placement job (GitHub Actions)<br/>1. region active?<br/>2. per group: cell with most headroom<br/>3. DBs on instances in same region;<br/>prod DB on the cell's own instance<br/>4. Cloud Run quota check (primary + DR)<br/>5. write placement.*"}}
  reg & cl & sq & cust & prods --> job

  job -- "headroom OK" --> commit["Bot commit to customer.yaml<br/>devstage: devstage-us-east1-02 / sql-nonprod-us-east1-01<br/>uat: uat-us-east1-01 / sql-nonprod-us-east1-01<br/>prod: prod-us-east1-01 / sql-prod-us-east1-01<br/>drCluster: prod-us-east1-01-dr"]
  job -- "region not active" --> fail1["PR fails:<br/>region not provisioned"]
  job -- "no headroom / quota" --> cap["Capacity PR (new cell) or quota PR<br/>platform approval → L2 apply<br/>customer PR fails until cell active"]

  subgraph east["us-east1 (active) ↔ DR pair us-central1"]
    c1["Dev/Stage cells<br/>devstage-us-east1-01, -02 (40 each)"]
    c2["UAT cells<br/>uat-us-east1-01 (40)"]
    c3["Prod cell prod-us-east1-01 (25)<br/>+ sql-prod-us-east1-01"]
    c3dr["prod-us-east1-01-dr + sql-prod-us-east1-01-dr<br/>(located in us-central1)"]
    c3 -. "DR pair" .-> c3dr
  end
  subgraph eu["europe-west1 (reserved) ↔ europe-west4"]
    r["IP ranges reserved<br/>nothing created until platform PR"]
  end
  commit --> east
```

IP plan per region per side: see the table in architecture §3. Pods come from `100.64.0.0/10`, so the region `/16` holds only nodes, services, Cloud Run egress, MIGs, proxies, PSC and PSA.
