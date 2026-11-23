# L0 Bootstrap

Run once, by a platform engineer with Organization Admin, from a laptop. It is a script, not
Terraform, because it creates what Terraform itself needs: the state bucket, the Terraform service
accounts and keyless CI federation.

| Creates | Notes |
|---|---|
| Folders `Platform/{Network,Compute,Data,Platform,Security,Dedicated-Customers}` | IDs go into the private copy of `inventory/platform.yaml` |
| Seed project `<prefix>-iac-seed` | Holds only IaC identities and state (outside the 12 fixed projects) |
| State bucket `<prefix>-tfstate` | Versioned, uniform access, public access prevention |
| `tf-l1`, `tf-nonprod`, `tf-prod` service accounts | `tf-l1` gets org/folder roles here; the per-side accounts get project roles from L1 |
| Workload identity pool `ci-pool` with `github` and `bitbucket` OIDC providers | Restricted to this repository on `main`, and to the product Bitbucket workspace |

```bash
export ORG_ID=000000000000 BILLING_ACCOUNT=000000-000000-000000 PREFIX=pfx \
       GITHUB_ORG=example-org BITBUCKET_WORKSPACE=example-workspace \
       BITBUCKET_WORKSPACE_UUID='{00000000-0000-0000-0000-000000000000}'
DRY_RUN=1 ./bootstrap.sh   # review every command
./bootstrap.sh
```

Then:
1. Record the printed IDs in the **private** overlay of `inventory/platform.yaml`. The public repo
   keeps placeholders only.
2. Create `infrastructure/backend.hcl` from `backend.hcl.example` (git-ignored).
3. Apply L1 from GitHub Actions, using the `l1-foundation` environment with required reviewers.
   The first apply runs on a GitHub-hosted runner with VPC-SC in dry-run. After that, L1 runs on
   the prod pool and `enforce_vpc_sc = true`.
