#!/usr/bin/env bash
# Promote an image from the non-prod to the prod Artifact Registry BY DIGEST (architecture §7, V11).
# Runs as promoter@<platform-prod>, the only identity allowed to read across the perimeters (VPC-SC
# egress rule on prod + ingress rule on non-prod, read methods only).
#
#   promote-by-digest.sh <product> <sha256:digest>
# Env: SRC, DST (registry paths), ATTESTOR (promoted), KMS_KEY_VERSION
set -euo pipefail

product="${1:?product}" digest="${2:?digest}"
: "${SRC:?}" "${DST:?}" "${ATTESTOR:?}" "${KMS_KEY_VERSION:?}"
[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo "bad digest" >&2; exit 2; }

src="${SRC}/${product}@${digest}"
dst="${DST}/${product}@${digest}"

# 1. The source must already carry the non-prod "built-and-signed" attestation.
gcloud beta container binauthz attestations list \
  --attestor="${ATTESTOR_BUILT:-${ATTESTOR/promoted/built-and-signed}}" \
  --artifact-url="$src" --format='value(name)' | grep -q . \
  || { echo "source image is not attested built-and-signed: $src" >&2; exit 1; }

# 2. Copy by digest: tags are never trusted across the boundary.
gcloud artifacts docker images copy "$src" "$dst" --quiet 2>/dev/null \
  || crane copy "$src" "$dst"

# 3. The digest must be unchanged on arrival.
got="$(gcloud artifacts docker images describe "$dst" --format='value(image_summary.digest)')"
[ "$got" = "$digest" ] || { echo "digest mismatch after copy: $got" >&2; exit 1; }

# 4. Attest "promoted": the prod Binary Authorization policy requires it (Decision 11).
gcloud beta container binauthz attestations sign-and-create \
  --artifact-url="$dst" --attestor="$ATTESTOR" --keyversion="$KMS_KEY_VERSION"

echo "promoted ${product}@${digest}"
