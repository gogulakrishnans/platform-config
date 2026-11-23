#!/usr/bin/env bash
# MIG delivery (architecture §13): new instance template from the promoted golden image (Packer),
# Ansible pre-steps (schema migration, expand phase), then a rolling update with a 10 % canary,
# maxUnavailable 0 and maxSurge 3 (one per zone), autohealing on. A failed health check stops the
# rollout and restores the previous template. L3 Terraform owns the MIG shape (C11).
#
#   mig-rolling-update.sh <customer> <product> <env> <version>
set -euo pipefail

customer="$1" product="$2" env="$3" version="$4"
root="$(cd "$(dirname "$0")/../.." && pwd)"
read -r short project region pair image < <(python3 - "$root" "$customer" "$product" "$env" "$version" <<'PY'
import sys, yaml, pathlib
root, c, p, e, v = pathlib.Path(sys.argv[1]), *sys.argv[2:]
plat = yaml.safe_load((root / "inventory/platform.yaml").read_text())
spec = yaml.safe_load((root / f"products/{p}/product.yaml").read_text())["spec"]
cust = yaml.safe_load((root / f"customers/{c}/customer.yaml").read_text())["spec"]
regions = {r["name"]: r for r in yaml.safe_load((root / "inventory/regions.yaml").read_text())["regions"]}
group = {"dev": "devstage", "stage": "devstage", "uat": "uat", "prod": "prod"}[e]
region = cust["region"]["primary"]
if e == "prod":
    image = yaml.safe_load((root / f"products/{p}/releases.yaml").read_text())["promoted"][v]
else:
    image = f"projects/{plat['projects']['platform-nonprod']['id']}/global/images/{spec['runtime']['imageFamily']}-{v.replace('.', '-')}"
print(spec["shortCode"], plat["projects"][plat["groups"][group]["computeProject"]]["id"], region, regions[region]["drPair"], image)
PY
)
mig="${customer}-${short}-${env}"
template="${mig}-${version//./-}-$(date -u +%Y%m%d%H%M)"

# The new template copies the current one (network tags, GSA, metadata, labels) and swaps the image.
current="$(gcloud compute instance-groups managed describe "$mig" --project "$project" --region "$region" \
           --format='value(versions[0].instanceTemplate.basename())')"
gcloud compute instance-templates create "$template" --project "$project" --region "$region" \
  --source-instance-template "projects/${project}/regions/${region}/instanceTemplates/${current}" \
  --image "$image" --quiet

# Schema migration (expand) and configuration through the Ansible runner pool before traffic moves.
ansible-playbook "$root/ansible/site.yml" -i "$root/ansible/inventory.gcp.yml" \
  -e "customer=${customer} product=${product} env=${env} version=${version} phase=pre-rollout"

# 10 % canary first, then the full rollout.
gcloud compute instance-groups managed rolling-action start-update "$mig" --project "$project" --region "$region" \
  --version "template=projects/${project}/regions/${region}/instanceTemplates/${current}" \
  --canary-version "template=projects/${project}/regions/${region}/instanceTemplates/${template},target-size=10%" \
  --max-unavailable 0 --max-surge 3 --quiet
gcloud compute instance-groups managed wait-until "$mig" --stable --project "$project" --region "$region" --timeout 1200 \
  || { echo "canary did not become healthy; restoring ${current}" >&2
       gcloud compute instance-groups managed rolling-action start-update "$mig" --project "$project" --region "$region" \
         --version "template=projects/${project}/regions/${region}/instanceTemplates/${current}" --max-unavailable 0 --max-surge 3 --quiet
       exit 1; }
gcloud compute instance-groups managed rolling-action start-update "$mig" --project "$project" --region "$region" \
  --version "template=projects/${project}/regions/${region}/instanceTemplates/${template}" \
  --max-unavailable 0 --max-surge 3 --quiet
gcloud compute instance-groups managed wait-until "$mig" --stable --project "$project" --region "$region" --timeout 1800

if [ "$env" = "prod" ]; then   # the DR MIG (minimum size) gets the same template
  gcloud compute instance-groups managed rolling-action start-update "${mig}" --project "$project" --region "$pair" \
    --version "template=projects/${project}/regions/${region}/instanceTemplates/${template}" --max-unavailable 0 --max-surge 3 --quiet
fi
echo "${mig} now runs ${version}"
