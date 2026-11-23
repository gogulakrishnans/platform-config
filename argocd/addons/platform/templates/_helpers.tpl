{{- define "platform.labels" -}}
customer: shared
environment: shared
env-group: {{ .Values.group }}
product: platform
region-role: {{ .Values.regionRole }}
managed-by: argocd
{{- end -}}
