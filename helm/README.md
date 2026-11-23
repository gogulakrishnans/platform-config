# Helm charts (D4)

Two platform-owned charts deliver everything that runs inside a GKE cluster for a customer. ArgoCD
deploys them (see [`argocd/`](../argocd/README.md)); Terraform never writes Kubernetes objects.

| Chart | One release per | Creates |
|---|---|---|
| [`tenant`](tenant/) | customer × environment × cluster (prod: primary and DR) | Namespace `{customer}-{env}` (Pod Security `restricted`, mesh injection), ResourceQuota (only the customer's StorageClass may be used), LimitRange, StorageClass `sc-{customer}-{env}` with the customer's CMEK key and the mandatory labels, default-deny NetworkPolicies with explicit allows (DNS, metadata server, restricted Google APIs, egress gateway, Cloud SQL), Istio PeerAuthentication STRICT, Sidecar `REGISTRY_ONLY`, RequestAuthentication, same-namespace AuthorizationPolicy, one KSA per GKE product for Workload Identity Federation |
| [`product-base`](product-base/) | customer × GKE product × environment × cluster | Argo Rollout (rolling, canary with Istio traffic split and analysis, or blue-green) or StatefulSet for an approved persistent volume, Services, HPA, PDB, PreSync migration Job, Cloud SQL Auth Proxy (native sidecar, IAM login, write endpoint), config file from the customer's product config, Istio VirtualService, DestinationRule, ingress AuthorizationPolicy (customer JWT claim), egress ServiceEntry allowlist |

## Values layers (product-base)

Applied in order, so later layers win:

| # | File | Owner | Holds |
|---|---|---|---|
| 1 | `helm/product-base/values.yaml` | Platform | Defaults: probes, strategy settings, security context, proxy image |
| 2 | `products/<product>/helm/values.yaml` | Product team | Image name, command, env, migration command, analysis thresholds |
| 3 | `products/<product>/helm/values-<env>.yaml` | Product team | Per-environment strategy and settings |
| 4 | `customers/<customer>/helm/<product>/values[-<env>].yaml` | Customer Success + product review | Optional per-customer overrides |
| 5 | `argocd/generated/<group>/products/<customer>-<product>-<env>[-dr].yaml` | Platform (generated) | Identity, image registry and version pin, sizing (catalog + `products.yaml` overrides), database, bucket/dataset/topic names, hosts, paths, egress allowlist, DR profile |

Layer 5 is written by `scripts/render-gitops.py` and is last, so the platform-injected keys cannot be
overridden. Both charts ship a strict `values.schema.json`, so a mistyped key fails `helm lint` and
`helm template`. This keeps the many values files from drifting.

## Rendered examples

[`examples/rendered/`](../examples/rendered/) has the expanded Applications and the rendered
manifests for both example customers in every group. `scripts/gitops-check.py` regenerates them.

## Checks

```bash
python scripts/gitops-check.py            # lint, expand ApplicationSets, template, kubeconform, policy
python -m pytest scripts/tests policy/tests
```
