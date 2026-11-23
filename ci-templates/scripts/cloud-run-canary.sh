#!/usr/bin/env bash
# Cloud Run progressive delivery (architecture §13): deploy the new version as a revision with no
# traffic, then shift 10 -> 25 -> 50 -> 100 %, checking the error rate after each step. Any failed
# check routes 100 % back to the previous revision. L3 Terraform owns the service shape and ignores
# the image/revision (C11); this step owns the version.
#
#   cloud-run-canary.sh <customer> <product> <env> <version>
# Env: REGISTRY_PROD, REGISTRY_NONPROD, STEP_WAIT (default 300 s), MAX_ERROR_RATE (default 0.01)
set -euo pipefail

customer="$1" product="$2" env="$3" version="$4"
root="$(cd "$(dirname "$0")/../.." && pwd)"
read -r short project region pair < <(python3 - "$root" "$customer" "$product" "$env" <<'PY'
import sys, yaml, pathlib
root, c, p, e = pathlib.Path(sys.argv[1]), *sys.argv[2:]
plat = yaml.safe_load((root / "inventory/platform.yaml").read_text())
spec = yaml.safe_load((root / f"products/{p}/product.yaml").read_text())["spec"]
cust = yaml.safe_load((root / f"customers/{c}/customer.yaml").read_text())["spec"]
regions = {r["name"]: r for r in yaml.safe_load((root / "inventory/regions.yaml").read_text())["regions"]}
group = {"dev": "devstage", "stage": "devstage", "uat": "uat", "prod": "prod"}[e]
region = cust["region"]["primary"]
print(spec["shortCode"], plat["projects"][plat["groups"][group]["computeProject"]]["id"], region, regions[region]["drPair"])
PY
)
service="${customer}-${short}-${env}"
if [ "$env" = "prod" ]; then
  digest="$(python3 -c "import yaml,sys; print(yaml.safe_load(open('$root/products/$product/releases.yaml'))['promoted']['$version'])")"
  image="${REGISTRY_PROD:?}/${product}@${digest}"
  regions="$region $pair"                     # the DR copy gets the same revision, no traffic split
else
  image="${REGISTRY_NONPROD:?}/${product}:${version}"
  regions="$region"
fi
tag="v${version//./-}"
wait="${STEP_WAIT:-300}"
max="${MAX_ERROR_RATE:-0.01}"

error_rate() {   # 5xx ratio of the tagged revision over the last step window (Cloud Monitoring)
  python3 "$root/ci-templates/scripts/error-rate.py" --project "$project" --service "$service" \
    --region "$1" --revision-tag "$tag" --window "$wait"
}

for r in $regions; do
  previous="$(gcloud run services describe "$service" --project "$project" --region "$r" \
              --format='value(status.traffic[0].revisionName)')"
  gcloud run deploy "$service" --project "$project" --region "$r" --image "$image" \
    --no-traffic --tag "$tag" --quiet
  if [ "$r" != "$region" ]; then
    gcloud run services update-traffic "$service" --project "$project" --region "$r" --to-tags "$tag=100" --quiet
    continue                                  # DR region: no live traffic to measure
  fi
  for pct in 10 25 50 100; do
    gcloud run services update-traffic "$service" --project "$project" --region "$r" --to-tags "$tag=$pct" --quiet
    [ "$pct" -eq 100 ] && break
    sleep "$wait"
    rate="$(error_rate "$r")"
    if python3 -c "import sys; sys.exit(0 if float('$rate') <= float('$max') else 1)"; then
      echo "step ${pct}%: error rate ${rate} ok"
    else
      echo "step ${pct}%: error rate ${rate} > ${max}; rolling back to ${previous}" >&2
      gcloud run services update-traffic "$service" --project "$project" --region "$r" --to-revisions "${previous}=100" --quiet
      exit 1
    fi
  done
done
echo "${service} now serves ${version}"
