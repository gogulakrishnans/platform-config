variable "enforce_vpc_sc" {
  description = "false until the self-hosted runners are live (perimeters in dry-run), then true."
  type        = bool
  default     = false
}

variable "argocd_chart_version" {
  description = "argo-helm argo-cd chart version (pinned; bumped by PR)."
  type        = string
  default     = "7.7.11"
}
