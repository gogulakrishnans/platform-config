#!/usr/bin/env bash
# Wait for a GKE product release to finish: ArgoCD syncs the new pin from the GitOps index, Argo
# Rollouts runs the canary with its analysis, and this script reports the outcome (L4 delivery).
# Reads Application status on the management cluster through the Connect Gateway (operator path).
#
#   argocd-wait.sh <customer> <product> <env>
# Env: MGMT_MEMBERSHIP_NONPROD, MGMT_MEMBERSHIP_PROD, PLATFORM_PROJECT, TIMEOUT (default 3600 s)
set -euo pipefail

customer="$1" product="$2" env="$3"
group="$( [ "$env" = prod ] && echo prod || { [ "$env" = uat ] && echo uat || echo devstage; } )"
ns="argocd-${group}"
membership="$( [ "$group" = prod ] && echo "${MGMT_MEMBERSHIP_PROD:?}" || echo "${MGMT_MEMBERSHIP_NONPROD:?}" )"
gcloud container fleet memberships get-credentials "$membership" --project "${PLATFORM_PROJECT:?}" >/dev/null

apps=("${customer}-${product}-${env}")
[ "$env" = prod ] && apps+=("${customer}-${product}-${env}-dr")
deadline=$(( $(date +%s) + ${TIMEOUT:-3600} ))

for app in "${apps[@]}"; do
  echo "waiting for ${app}"
  while :; do
    status="$(kubectl -n "$ns" get application "$app" -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null || echo "Missing/Missing")"
    case "$status" in
      Synced/Healthy) echo "${app}: ${status}"; break ;;
      */Degraded) echo "${app}: ${status} (canary aborted and rolled back by Argo Rollouts)" >&2; exit 1 ;;
    esac
    [ "$(date +%s)" -lt "$deadline" ] || { echo "${app}: timed out at ${status}" >&2; exit 1; }
    sleep 30
  done
done
