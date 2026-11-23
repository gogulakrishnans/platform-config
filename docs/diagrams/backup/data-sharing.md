# Data-sharing flows (within one customer) (Mermaid, backup)

Backup of the Mermaid version. The current diagram is the Google Cloud icon version on [../data-sharing.md](../data-sharing.md).

Three one-way, audited flows. No live cross-environment connections, and no path between customers. See [architecture §9](../../architecture.md#9-data-sharing-within-a-customer).

```mermaid
flowchart LR
  subgraph np["Non-prod perimeter"]
    dev["acme-corp dev"]
    stage["acme-corp stage"]
    uat["acme-corp uat"]
    imp["Non-prod import job (data-nonprod)<br/>drop + recreate acme_corp_uat<br/>import as target login<br/>rerun bootstrap"]
  end

  subgraph ex["Exchange perimeter (data-exchange)"]
    shared[("pfx-acme-corp-shared<br/>acme_corp_shared")]
    seed[("pfx-acme-corp-seed<br/>sanitized dumps")]
  end

  subgraph pr["Prod perimeter"]
    prod["acme-corp prod<br/>acme_corp_prod"]
    subgraph sd["Seed-down (data-prod)"]
      s1["1. Cloud SQL export"]
      s2["2. import to scratch instance"]
      s3["3. sanitize.sql → verify.sql<br/>→ _clone_metadata"]
      s4["4. NOLOGIN role = target login<br/>REASSIGN OWNED"]
      s5["5. export → seed bucket<br/>delete scratch"]
      s1 --> s2 --> s3 --> s4 --> s5
    end
    promo["Promote pipeline (prod pool)<br/>approval per step"]
  end

  %% shared reference
  promo -- "write after approval" --> shared
  shared -. "read only" .-> dev & stage & uat & prod

  %% promote up
  dev -- "export package" --> stage -- "approval" --> uat -- "approval (customer-success)" --> promo --> prod

  %% seed down
  prod --> s1
  s5 -- "write seed dumps only" --> seed
  seed -- "read (non-prod identity pulls)" --> imp --> uat
  imp -. "if in seedDown.targets" .-> stage

  s3 -- "verification fails" --> stop(["alert + stop<br/>target unusable"])
```

| Flow | Policy (`data-sharing.yaml`) | Guard |
|---|---|---|
| Shared reference | `sharedReference: true` | Written only by the promote pipeline |
| Promote up | `promoteUp: { enabled, approvals }` | Approval per step, version-compatibility window, product export/import support |
| Seed down | `seedDown: { targets, mode: sanitized, schedule }` | Mandatory sanitization + verification, version-compatibility window, same region, no prod identity writes to non-prod |

BigQuery seed down uses a scheduled anonymizing query into the exchange dataset. GCS uses Storage Transfer Service with sensitive prefixes excluded. PVCs and Pub/Sub messages are never shared.
