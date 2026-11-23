# Resource hierarchy and VPC-SC perimeters (Mermaid, backup)

Backup of the Mermaid version. The current diagram is the Google Cloud icon version on [../hierarchy.md](../hierarchy.md).

Regions and cells are resources inside the fixed projects, not projects. See [architecture §2](../../architecture.md#2-resource-hierarchy-and-project-model).

```mermaid
flowchart TB
  org["Organization (000000000000)<br/>org policies: resourceLocations, no external IP, no SA keys,<br/>OS Login, Shielded VM, trusted images, CMEK required"]
  org --> plat["Folder: Platform"]

  plat --> fnet["Folder: Network"]
  plat --> fcomp["Folder: Compute"]
  plat --> fdata["Folder: Data"]
  plat --> fplat["Folder: Platform"]
  plat --> fsec["Folder: Security"]
  plat --> fded["Folder: Dedicated-Customers<br/>(only isolation: dedicated)"]

  subgraph NP["VPC-SC perimeter: non-prod"]
    netnp["net-nonprod<br/>Shared VPC host · vpc-nonprod<br/>subnets per region · NAT"]
    cds["compute-devstage<br/>cells: devstage-&lt;region&gt;-NN"]
    cu["compute-uat<br/>cells: uat-&lt;region&gt;-NN"]
    dnp["data-nonprod<br/>sql-nonprod-&lt;region&gt;-NN"]
    pnp["platform-nonprod<br/>mgmt cluster · ArgoCD DS + UAT<br/>runners · AR non-prod"]
    snp["security-nonprod<br/>customer key rings · build signer"]
  end

  subgraph PR["VPC-SC perimeter: prod"]
    netp["net-prod<br/>Shared VPC host · vpc-prod"]
    cp["compute-prod<br/>cells: prod-&lt;region&gt;-NN + -dr<br/>global LB · Cert Manager"]
    dp["data-prod<br/>sql-prod-&lt;region&gt;-NN + DR replicas<br/>seed-down function + scratch"]
    pp["platform-prod<br/>mgmt cluster · ArgoCD Prod<br/>runners · AR prod · metrics scope"]
    sp["security-prod<br/>customer key rings · prod attestor<br/>log sinks · SCC"]
  end

  subgraph EX["VPC-SC perimeter: exchange"]
    dx["data-exchange<br/>per customer: shared bucket, shared dataset,<br/>seed bucket, exchange key ring"]
  end

  fnet --> netnp & netp
  fcomp --> cds & cu & cp
  fdata --> dnp & dp & dx
  fplat --> pnp & pp
  fsec --> snp & sp
  fded --> dc["Folder: {customer} → {customer}-dedicated<br/>(project factory)"]

  netnp -. "Shared VPC service projects" .- cds & cu & dnp & pnp
  netp -. "Shared VPC service projects" .- cp & dp & pp

  PR -- "read own shared ref · write seed dumps · promote shared ref" --> EX
  NP -- "read own shared ref · read seed dumps" --> EX
  PR -- "promoter: read AR non-prod only" --> NP

  classDef prodC fill:#fde7e7,stroke:#c62828,color:#000
  classDef nonprodC fill:#e8f1fd,stroke:#1565c0,color:#000
  classDef exC fill:#e9f7ef,stroke:#2e7d32,color:#000
  class PR prodC
  class NP nonprodC
  class EX exC
```
