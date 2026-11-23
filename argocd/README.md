# ArgoCD (architecture §14)

There are three instances, one per environment group. Each instance can reach only its own group's clusters.

| Instance | Runs on | Targets | Policy |
|---|---|---|---|
| `argocd-devstage` | `platform-nonprod` management cluster | Dev/Stage clusters | generators may delete Applications |
| `argocd-uat` | `platform-nonprod` management cluster | UAT clusters | generators may delete Applications |
| `argocd-prod` | `platform-prod` management cluster | Prod clusters and their DR clusters | **create and update only**, the root never prunes, product sync window |

## Bootstrap

L1 Terraform installs the `argo-cd` chart and one **root Application** per instance (the ArgoCD
release's `extraObjects`). This is the only Terraform-to-cluster step (C17). The root Application
deploys [`root/`](root/) with `values-<group>.yaml` and `generated/<group>/root.yaml`.

## What the root chart renders

```
root (app-of-apps, argocd/root)
├── Secret cluster-<name>          one per cluster, credential-free: DNS endpoint + argocd-k8s-auth gcp
├── AppProject platform-addons     add-ons, cluster-scoped resources allowed
├── AppProject platform-tenants    tenant chart: Namespace + StorageClass + guardrails only
├── AppProject <customer>          products only, the customer's namespaces only, allowlisted kinds
├── ApplicationSet addon-*         cluster generator: cert-manager, argo-rollouts, falco, mesh, platform
├── ApplicationSet tenants         git files generator: generated/<group>/tenants/*.yaml   -> helm/tenant
└── ApplicationSet products        git files generator: generated/<group>/products/*.yaml  -> helm/product-base
```

## The GitOps index (`generated/`)

`scripts/render-gitops.py` joins four sources and writes one file per Application:
- the customer (placement and options)
- the catalog (runtime, sizing, routing and egress)
- the version pins and overrides in `products.yaml`
- the cell inventory (DR state and SQL write endpoint)

Each file:
- holds the ApplicationSet parameters in an `argocd:` block
- is the Application's last values layer
- is created or removed when a customer, product or cell changes

Do not edit these files by hand. The PR pipeline regenerates them and fails if the committed copy is out of date. See decisions #26.

## Local add-on charts

| Chart | Contents |
|---|---|
| [`addons/mesh`](addons/mesh/) | Ingress gateway, with zonal NEGs `neg-istio-<cluster>` used by the L2-edge load balancer. Egress gateway, with the gateway leg of the catalog egress allowlist. Mesh-wide STRICT mTLS. JWT `RequestAuthentication` plus a deny-without-token policy on `/v*`. cert-manager certificate for TLS from the load balancer to the gateway. |
| [`addons/platform`](addons/platform/) | `istio-golden-signals` ClusterAnalysisTemplate (canary error rate and p95 latency). `mandatory-labels` ValidatingAdmissionPolicy. Istio `ClusterPodMonitoring`. Managed Prometheus query frontend for Argo Rollouts. |

Remote charts are pinned by version in [`root/values.yaml`](root/values.yaml).

## Checks

`python scripts/gitops-check.py` expands every ApplicationSet the way ArgoCD does (goTemplate,
`missingkey=error`). It then renders every in-repo Application with its exact value files and validates
the result with kubeconform and `policy/check_manifests.py`. The output is in [`examples/rendered/`](../examples/rendered/).
