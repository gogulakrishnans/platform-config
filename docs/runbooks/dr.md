# Runbook: DR failover and failback (per cell)

Scope: one **prod cell**, meaning one cluster and one Cloud SQL instance with their customers, moving to its
DR pair region. Targets: warm standby RTO ~30 min / RPO ~5 min, hot standby ~5 min / ~1 min
(architecture §12). Failover is per cell: other cells are untouched, and DR clusters are dedicated.

## Decide
- Declare when the primary region of the cell is impaired for more than 10 minutes, or Google declares a regional incident.
- Incident commander: SRE on call. Approver for the prod pool: platform lead.

## Failover (T = declaration)
| T+ | Step | Command / change |
|---|---|---|
| 0 | Freeze deploys to the cell: pause the prod ApplicationSet sync window and `l4-delivery` | Close the sync window on the customers' AppProjects; disable the `l4-delivery` workflow |
| 2 | Promote the Cloud SQL DR replica | `gcloud sql instances promote-replica sql-prod-<region>-<nn>-dr --failover` |
| 7 | Check the write endpoint now resolves to the new primary | `dig +short sql-prod-<region>-<nn>.<write-endpoint-zone>`. Fallback: switch the per-region connection setting (verification V9) |
| 8 | Scale DR compute: the DR cluster node pool to the cell size; Cloud Run min instances; DR MIG size | PR in step 9 does this; for speed, `gcloud container clusters resize` and `gcloud compute instance-groups managed resize` |
| 9 | **Git PR:** `drActive: true` for the cell in `inventory/regions.yaml` | Merge → `terraform-apply` (prod pool, `tf-prod` approval): the edge sets DR backends to capacity 1 and primary to 0; L2 sizes the DR cluster; `render-gitops` gives DR Applications full replicas |
| 15 | Re-point Pub/Sub push subscriptions to the DR Cloud Run services | Applied by the same L3 apply (subscription endpoints follow `drActive`) |
| 20 | Verify: SLO dashboards, synthetic checks per customer host, `isolation-tests` for prod | `gh workflow run isolation-tests.yml -f environment=prod` |
| 30 | Communicate the RTO actually reached; keep the freeze until failback | |

**Data notes:**
- GCS dual-region buckets need no action.
- BigQuery uses the DR dataset (daily copy, RPO 24 h). It isn't part of the online path.
- Backup for GKE restores PVCs of stateful products into the DR cluster:
  ```bash
  gcloud beta container backup-restore restores create ...
  ```

## Failback (after the region is healthy)
1. Recreate the replica in the original region from the new primary. Wait until replication lag is under 1 second.
2. Run a switchover with no data loss, in a maintenance window: `gcloud sql instances switchover <replica>`.
3. **Git PR:** set `drActive: false`. The edge moves traffic back and the DR cluster returns to minimum size.
4. Lift the freeze. Do the post-incident review within 5 business days.

## Quarterly DR test (per cell, required)
- Run the full failover on a **switchover** (planned, no data loss) in a low-traffic window.
- Measure RTO and RPO, then fail back.
- Record the results in the DR test log. Any miss against the target becomes an action item.

## Rebuild the Prod ArgoCD instance in the pair region
ArgoCD holds no state that isn't in Git.
1. Create a management cluster in the pair region: L1 change to the `platform` module region. Or use the standby management cluster if one is provisioned.
2. Apply L1 with the `argocd_prod` release pointed at it. This installs ArgoCD and its root Application.
3. The root Application re-creates the cluster Secrets, AppProjects and ApplicationSets from Git. Applications are adopted without redeploying: the annotation tracking ID matches.
4. Grant the new ArgoCD service account `container.admin` on `compute-prod`. This is the L1 output (decisions #22).

Time: about 45 minutes, most of it cluster creation.
