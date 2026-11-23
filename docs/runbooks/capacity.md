# Runbook: capacity (cells) and regions

## Add a cell (placement exit 3, or quota above 80%)
Placement writes a capacity request (`--request-file`), for example
`{"kind": "cell", "region": "us-east1", "group": "uat", ...}`.

1. **Platform PR to `inventory/regions.yaml`:** add the cell with the next free **slot** under `cells.<group>` in that region.
   - The slot fixes the cell's `/24` node subnet and its pod and service ranges (architecture §3, decisions #23).
   - Prod cells also need a `drSlot` in the pair region, with `drActive: false`.
   ```yaml
   uat:
     - { id: "01", slot: 3 }
     - { id: "02", slot: 4 }      # new
   ```
   For a SQL request, add `- { id: "02" }` under `sqlInstances.nonprod`. A prod instance comes with its prod cell.
2. `generate-layers.py --check` stays clean: the L2 roots are per region and group, so no new root is needed.
3. **Merge.** `terraform-apply` runs the L2-region state for that region and group on the group's pool. It creates:
   - the subnet
   - the cluster (and DR cluster)
   - the SQL instance (and DR replica)
   - the inventory files, `inventory/clusters/*.yaml` and `inventory/sql/*.yaml`, written back by the apply
4. ArgoCD registers the new cluster from the generated `root.yaml` and installs the add-ons.
5. Re-run placement for the waiting customer: re-run the `customer-pr` job.

Time: about 25–40 minutes, most of it cluster creation (about 10 min) and SQL instance creation (about 15 min).

## Add a region
1. **Check reserved ranges:** the region must already exist in `regions.yaml` with `status: reserved`. If not, add it first with a new `/16` per side and a `/13` `podCidr` from the plan in architecture §3.
2. **Prod needs its DR pair.** Both regions of a pair become active in the same PR: a prod region cannot be active without its pair.
3. **Platform PR:**
   - set `status: active`
   - add cells (with slots) and `sqlInstances.nonprod`
   - add the region's quotas (`cloudRunServices`)
4. **`generate-layers.py`** adds the L2 roots (`L2-region/<region>/{devstage,uat,prod}`) and the Dev/Stage edge root (`L2-edge/devstage-<region>`).
5. **Org policy:** L1 adds the region to the allowed locations (`gcp.resourceLocations`). This change triggers the L1 wave.
6. **Merge:** L1 → L2-region → L2-edge. Request the project quotas for the new region (`modules/project-factory` quota preferences).
7. Customers can now choose the region in `region.primary`.

Approval: one platform PR with the security and platform code owners. No project is created: the project count stays at 12.
