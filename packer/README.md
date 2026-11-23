# Packer: golden images for MIG products

One minimal working template ([`legacy-billing.pkr.hcl`](legacy-billing.pkr.hcl)). The image path is:

1. **Build.** A release of a MIG product triggers `packer build` on the non-prod runner pool. The build VM uses an internal IP and IAP SSH, with no external IP. The image goes into `platform-nonprod`, image family `legacy-billing`, and is encrypted with the platform key. The shared Ansible role ([`../ansible`](../ansible)) runs with `phase=bake`: OS hardening, runtime, release bundle, systemd unit.
2. **Promote.** The promoter copies the image into `platform-prod` and records it in `products/legacy-billing/releases.yaml`. The promoter is the only identity allowed to read across the perimeters (V11). The org policy `compute.trustedImageProjects` allows only these two projects (C8).
3. **Roll out.** `ci-templates/scripts/mig-rolling-update.sh` creates a new instance template from the image. It then runs Ansible with `phase=pre-rollout` for the schema migration (expand) and does a rolling update with a 10% canary.

```bash
packer init .
packer validate -var-file=example.pkrvars.hcl .
```

There's one image per product release. Customer configuration is never baked into an image. It comes from instance metadata and Secret Manager at boot.
