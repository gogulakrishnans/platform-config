# Runbook: Binary Authorization break-glass

Prod admits only images attested **promoted**, which means copied by digest from a built-and-signed
non-prod image (Decision 11). Break-glass deploys an unattested image during an incident when the
promotion path is unavailable. Every use is logged and alerts, and must be reviewed.

## When
- **Allowed:** a prod outage whose fix can't wait for the normal build → sign → promote path, about 20 minutes. Examples: the attestor's KMS key is unavailable, or the promotion pipeline is down.
- **Never:** to skip a failed vulnerability scan or a failed review.

## How
**GKE.** Add the break-glass annotation to the pod template, through a product values layer in a PR
to `customers/<id>/helm/<product>/values-prod.yaml`:
```yaml
podAnnotations:
  alpha.image-policy.k8s.io/break-glass: "true"
```
The image must still be referenced by digest; the manifest policy enforces that.

**Cloud Run:**
```bash
gcloud run deploy <service> --image <image@digest> --binary-authorization=default \
  --breakglass="INC-1234: <reason>"
```

**MIG:** images come only from the trusted image projects, through the org policy. Break-glass is a manual image copy into `platform-prod` by the promoter, with the incident ID in the image description.

## Controls
- **Audit and alerting:**
  - Cloud Audit Logs records every break-glass admission: `binaryauthorization.googleapis.com` with `breakglass`.
  - A log-based alert pages security and the platform lead.
- **Follow-up:**
  - Within 24 hours, the image goes through the normal path (build-sign → promote).
  - A PR removes the annotation.
  - The incident record links both.
- **Review:** the security review checks every use (see [../security-operations.md](../security-operations.md)).
