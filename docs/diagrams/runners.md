# Shared CI and Ansible runner topology

See [architecture §15](../architecture.md#15-shared-ci-and-ansible-runners).

```mermaid
flowchart TB
  gh(["GitHub: platform-config + product repos"])
  bb(["Bitbucket: product repos"])
  fork(["Fork PRs (public repo)"])

  fork -- "offline checks only, no secrets" --> hosted["GitHub-hosted runners"]

  subgraph np["platform-nonprod · non-prod perimeter"]
    ghnp["GitHub ARC pool (non-prod)<br/>TF L2/L3 non-prod · placement · image builds · Packer"]
    bbnp["Bitbucket runner pool<br/>build · scan · sign (non-prod key) · push"]
    ansnp["Ansible runners (non-prod MIG)<br/>OS Login · IAP-only SSH"]
    arnp[("AR non-prod")]
  end

  subgraph pr["platform-prod · prod perimeter"]
    ghp["GitHub ARC pool (prod)<br/>TF L1 (extra approval) · L2/L3 prod<br/>image promotion · Cloud Run/MIG deploy"]
    ansp["Ansible runners (prod MIG)"]
    arp[("AR prod (multi-region)")]
  end

  gh -- "protected branch + GitHub Environments<br/>OIDC → WIF" --> ghnp & ghp
  bb -- "Bitbucket OIDC → WIF" --> bbnp
  ghnp & bbnp --> arnp
  arnp -- "promote by digest + prod attestation<br/>(only cross-perimeter read)" --> ghp --> arp
  ansnp --> m1["non-prod MIGs (private IP)"]
  ansp --> m2["prod MIGs (private IP)"]

  nat["Cloud NAT → github.com / bitbucket.org"]
  ghnp & bbnp & ghp -.-> nat
```

| Property | Value |
|---|---|
| Lifetime | Ephemeral, one job per runner |
| Network | No public IP, inside the VPC-SC perimeter, egress through Cloud NAT |
| Auth | WIF (GitHub OIDC, Bitbucket OIDC), no keys |
| Scope | Non-prod pool identity: non-prod projects only. Prod pool identity: prod projects plus the non-prod AR read |
