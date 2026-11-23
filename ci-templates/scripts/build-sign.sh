#!/usr/bin/env bash
# Build, scan and sign a product image (non-prod registry). Used by the GitHub composite action and
# the Bitbucket template. Requires: docker (buildx), gcloud, an authenticated ci-builder identity.
#
#   build-sign.sh build  <product> <version> <context>      -> prints digest=... and image=...
#   build-sign.sh scan   <image@digest> <max-severity>       fail on findings >= severity
#   build-sign.sh attest <image@digest> <attestor> <kms-key-version>
set -euo pipefail

cmd="${1:?usage: build-sign.sh build|scan|attest ...}"
shift

case "$cmd" in
  build)
    product="$1" version="$2" context="${3:-.}"
    : "${REGISTRY:?REGISTRY (non-prod Artifact Registry path) is required}"
    [[ "$version" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "bad version $version" >&2; exit 2; }
    version="${version#v}"
    repo="${REGISTRY}/${product}"
    gcloud auth configure-docker "${REGISTRY%%/*}" --quiet >&2
    docker buildx build "$context" \
      --tag "${repo}:${version}" \
      --label "org.opencontainers.image.version=${version}" \
      --provenance=mode=max --sbom=true \
      --push --metadata-file /tmp/build-metadata.json >&2
    digest="$(jq -r '."containerimage.digest"' /tmp/build-metadata.json)"
    echo "digest=${digest}"
    echo "image=${repo}@${digest}"
    ;;

  scan)
    image="$1" max="${2:-HIGH}"
    # Artifact Analysis on-demand scanning; the registry's continuous scanning also covers it later.
    scan="$(gcloud artifacts docker images scan "$image" --remote --format='value(response.scan)')"
    levels="CRITICAL"
    [ "$max" = "HIGH" ] && levels="CRITICAL HIGH"
    [ "$max" = "MEDIUM" ] && levels="CRITICAL HIGH MEDIUM"
    found=0
    for sev in $levels; do
      n="$(gcloud artifacts docker images list-vulnerabilities "$scan" \
            --format='value(vulnerability.effectiveSeverity)' | grep -c "^${sev}$" || true)"
      echo "${sev}: ${n}"
      found=$((found + n))
    done
    [ "$found" -eq 0 ] || { echo "vulnerabilities at or above ${max}: ${found}" >&2; exit 1; }
    ;;

  attest)
    image="$1" attestor="$2" key_version="$3"
    # Binary Authorization: the non-prod policy requires "built-and-signed" (Decision 11).
    gcloud beta container binauthz attestations sign-and-create \
      --artifact-url="$image" \
      --attestor="$attestor" \
      --keyversion="$key_version"
    ;;

  *)
    echo "unknown command $cmd" >&2
    exit 2
    ;;
esac
