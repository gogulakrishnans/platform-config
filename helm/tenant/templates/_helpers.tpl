{{/* Namespace: {customer}-{env} (architecture §16). */}}
{{- define "tenant.namespace" -}}
{{ printf "%s-%s" .Values.customer .Values.environment }}
{{- end -}}

{{/* The six mandatory labels (decisions #9). Tenant objects belong to the platform. */}}
{{- define "tenant.labels" -}}
{{ include "tenant.labelsFor" (dict "Values" .Values "Chart" .Chart "product" "platform") }}
{{- end -}}

{{/* Same labels for an object that belongs to one product (e.g. its KSA). */}}
{{- define "tenant.labelsFor" -}}
customer: {{ .Values.customer }}
environment: {{ .Values.environment }}
env-group: {{ .Values.envGroup }}
product: {{ .product }}
region-role: {{ .Values.regionRole }}
managed-by: argocd
app.kubernetes.io/part-of: tenant
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Prod objects that must never be removed by a sync (deletion goes through decommission). */}}
{{- define "tenant.protect" -}}
{{- if eq .Values.environment "prod" }}
argocd.argoproj.io/sync-options: Delete=false
{{- end }}
{{- end -}}
