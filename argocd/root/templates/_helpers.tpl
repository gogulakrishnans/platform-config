{{- define "root.ns" -}}
{{ printf "argocd-%s" .Values.group }}
{{- end -}}

{{- define "root.labels" -}}
customer: shared
environment: shared
env-group: {{ .Values.group }}
product: platform
region-role: primary
managed-by: argocd
{{- end -}}

{{/* ApplicationSet safety policy for this instance. */}}
{{- define "root.appsetSyncPolicy" -}}
applicationsSync: {{ .Values.policy.applicationsSync }}
preserveResourcesOnDeletion: {{ .Values.policy.preserveResourcesOnDeletion }}
{{- end -}}

{{/* Application sync policy. Call with (dict "Values" .Values "extra" (list ...)). */}}
{{- define "root.appSyncPolicy" -}}
automated:
  prune: true
  selfHeal: true
syncOptions:
  - ServerSideApply=true
  - PruneLast=true
  - RespectIgnoreDifferences=true
  {{- range .extra }}
  - {{ . }}
  {{- end }}
retry:
  {{- toYaml .Values.retry | nindent 2 }}
{{- end -}}
