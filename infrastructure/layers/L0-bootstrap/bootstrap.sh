#!/usr/bin/env bash
# L0 Bootstrap (manual, once, from a platform engineer's laptop). See README.md in this directory.
#
# Creates: top-level folders, the IaC seed project, the Terraform state bucket, the Terraform
# service accounts (tf-l1, tf-nonprod, tf-prod) and GitHub + Bitbucket -> GCP identity federation.
# No service-account keys are created anywhere.
#
# Usage:
#   export ORG_ID=... BILLING_ACCOUNT=... PREFIX=pfx GITHUB_ORG=... BITBUCKET_WORKSPACE_UUID=... \
#          BITBUCKET_WORKSPACE=... REGION=us-east1
#   DRY_RUN=1 ./bootstrap.sh     # print every command first (recommended)
#   ./bootstrap.sh
#
# Idempotent: every step checks for the resource first. Re-running is safe.
set -euo pipefail

: "${ORG_ID:?set ORG_ID}"
: "${BILLING_ACCOUNT:?set BILLING_ACCOUNT}"
: "${PREFIX:?set PREFIX (bucket/project prefix, e.g. pfx)}"
: "${GITHUB_ORG:?set GITHUB_ORG}"
: "${BITBUCKET_WORKSPACE:?set BITBUCKET_WORKSPACE}"
: "${BITBUCKET_WORKSPACE_UUID:?set BITBUCKET_WORKSPACE_UUID (with braces)}"
REGION="${REGION:-us-east1}"
REPO="${REPO:-platform-config}"
SEED_PROJECT="${PREFIX}-iac-seed"
STATE_BUCKET="${PREFIX}-tfstate"
DRY_RUN="${DRY_RUN:-0}"

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" != "1" ]]; then "$@"; fi
}

exists() { [[ "$DRY_RUN" == "1" ]] && return 1; "$@" >/dev/null 2>&1; }

folder_id() { # name parent
  gcloud resource-manager folders list --"${2%%s/*}"="${2##*/}" \
    --filter="displayName=$1" --format="value(name)" 2>/dev/null | head -n1
}

ensure_folder() { # name parent(organizations/N|folders/N) -> echoes folders/ID
  local id
  id="$(folder_id "$1" "$2" || true)"
  if [[ -z "$id" ]]; then
    run gcloud resource-manager folders create --display-name="$1" --"${2%%s/*}"="${2##*/}" >&2
    id="$(folder_id "$1" "$2" || echo "folders/DRY-RUN-$1")"
  fi
  echo "$id"
}

echo "== 1. Folders"
PLATFORM_FOLDER="$(ensure_folder Platform "organizations/${ORG_ID}")"
declare -A FOLDERS
for f in Network Compute Data Platform Security Dedicated-Customers; do
  FOLDERS[$f]="$(ensure_folder "$f" "$PLATFORM_FOLDER")"
done

echo "== 2. Seed project and state bucket"
if ! exists gcloud projects describe "$SEED_PROJECT"; then
  run gcloud projects create "$SEED_PROJECT" --folder="${FOLDERS[Platform]#folders/}" --labels=customer=shared,environment=shared,env-group=shared,product=platform,region-role=primary,managed-by=terraform
fi
run gcloud billing projects link "$SEED_PROJECT" --billing-account="$BILLING_ACCOUNT"
run gcloud services enable --project="$SEED_PROJECT" \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com cloudbilling.googleapis.com storage.googleapis.com orgpolicy.googleapis.com \
  accesscontextmanager.googleapis.com cloudquotas.googleapis.com

if ! exists gcloud storage buckets describe "gs://${STATE_BUCKET}"; then
  run gcloud storage buckets create "gs://${STATE_BUCKET}" --project="$SEED_PROJECT" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention
fi
run gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning \
  --update-labels=customer=shared,environment=shared,env-group=shared,product=platform,region-role=primary,managed-by=terraform

echo "== 3. Terraform service accounts"
for sa in tf-l1 tf-nonprod tf-prod; do
  if ! exists gcloud iam service-accounts describe "${sa}@${SEED_PROJECT}.iam.gserviceaccount.com"; then
    run gcloud iam service-accounts create "$sa" --project="$SEED_PROJECT" --display-name="Terraform ${sa#tf-}"
  fi
  run gcloud storage buckets add-iam-policy-binding "gs://${STATE_BUCKET}" \
    --member="serviceAccount:${sa}@${SEED_PROJECT}.iam.gserviceaccount.com" --role=roles/storage.objectAdmin
done

TF_L1="serviceAccount:tf-l1@${SEED_PROJECT}.iam.gserviceaccount.com"
for role in roles/orgpolicy.policyAdmin roles/accesscontextmanager.policyAdmin roles/compute.xpnAdmin \
            roles/billing.viewer roles/resourcemanager.organizationViewer; do
  run gcloud organizations add-iam-policy-binding "$ORG_ID" --member="$TF_L1" --role="$role" --condition=None
done
for role in roles/resourcemanager.projectCreator roles/resourcemanager.folderViewer roles/resourcemanager.projectIamAdmin \
            roles/serviceusage.serviceUsageAdmin roles/editor roles/iam.serviceAccountAdmin roles/cloudkms.admin \
            roles/container.admin roles/compute.networkAdmin roles/logging.configWriter; do
  run gcloud resource-manager folders add-iam-policy-binding "${PLATFORM_FOLDER#folders/}" --member="$TF_L1" --role="$role"
done
run gcloud billing accounts add-iam-policy-binding "$BILLING_ACCOUNT" --member="$TF_L1" --role=roles/billing.user
# tf-nonprod / tf-prod receive their roles from L1 once the fixed projects exist (layers/L1-foundation).

echo "== 4. Identity federation (keyless CI)"
POOL=ci-pool
if ! exists gcloud iam workload-identity-pools describe "$POOL" --project="$SEED_PROJECT" --location=global; then
  run gcloud iam workload-identity-pools create "$POOL" --project="$SEED_PROJECT" --location=global \
    --display-name="GitHub and Bitbucket CI"
fi
# GitHub: only this repository; L1 only from the protected "l1-foundation" environment.
if ! exists gcloud iam workload-identity-pools providers describe github --project="$SEED_PROJECT" --location=global --workload-identity-pool="$POOL"; then
  run gcloud iam workload-identity-pools providers create-oidc github --project="$SEED_PROJECT" --location=global \
    --workload-identity-pool="$POOL" --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_ORG}/${REPO}' && assertion.ref=='refs/heads/main'"
fi
# Bitbucket: only the product workspace, used by the build/scan/sign pipelines (no Terraform).
if ! exists gcloud iam workload-identity-pools providers describe bitbucket --project="$SEED_PROJECT" --location=global --workload-identity-pool="$POOL"; then
  run gcloud iam workload-identity-pools providers create-oidc bitbucket --project="$SEED_PROJECT" --location=global \
    --workload-identity-pool="$POOL" \
    --issuer-uri="https://api.bitbucket.org/2.0/workspaces/${BITBUCKET_WORKSPACE}/pipelines-config/identity/oidc" \
    --allowed-audiences="ari:cloud:bitbucket::workspace/${BITBUCKET_WORKSPACE_UUID//[\{\}]/}" \
    --attribute-mapping="google.subject=assertion.sub,attribute.workspace=assertion.workspaceUuid" \
    --attribute-condition="assertion.workspaceUuid=='${BITBUCKET_WORKSPACE_UUID}'"
fi

POOL_ID="$(gcloud iam workload-identity-pools describe "$POOL" --project="$SEED_PROJECT" --location=global --format='value(name)' 2>/dev/null || echo "projects/N/locations/global/workloadIdentityPools/${POOL}")"
run gcloud iam service-accounts add-iam-policy-binding "tf-l1@${SEED_PROJECT}.iam.gserviceaccount.com" \
  --project="$SEED_PROJECT" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.environment/l1-foundation"

echo "== 5. Record these values in inventory/platform.yaml (private overlay, never committed)"
echo "folders.platform: ${PLATFORM_FOLDER}"
for f in "${!FOLDERS[@]}"; do echo "folders.${f}: ${FOLDERS[$f]}"; done
echo "iac.seedProject.id: ${SEED_PROJECT}"
echo "iac.stateBucket: ${STATE_BUCKET}"
echo "workloadIdentityPool: ${POOL_ID}"
echo
echo "Next: migrate this layer's local state is not needed (L0 is a script). Apply L1 from GitHub Actions"
echo "(environment l1-foundation, GitHub-hosted runner, VPC-SC in dry-run). See infrastructure/README.md."
