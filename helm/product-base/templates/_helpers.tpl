{{/* Namespace and workload name. The namespace comes from the tenant chart: {customer}-{env}. */}}
{{- define "product.namespace" -}}
{{ printf "%s-%s" .Values.customer .Values.environment }}
{{- end -}}

{{- define "product.name" -}}
{{ .Values.product.shortCode }}
{{- end -}}

{{- define "product.host" -}}
{{ printf "%s.%s.svc.cluster.local" .Values.product.shortCode (include "product.namespace" .) }}
{{- end -}}

{{/* Workload kind and update strategy actually used. The DR cluster always rolls plainly:
     it carries no user traffic for a canary analysis to measure. */}}
{{- define "product.kind" -}}
{{ ternary "StatefulSet" "Rollout" .Values.persistence.enabled }}
{{- end -}}

{{- define "product.strategy" -}}
{{- if or .Values.persistence.enabled (eq .Values.regionRole "dr") -}}
rolling
{{- else -}}
{{ .Values.strategy.type }}
{{- end -}}
{{- end -}}

{{/* The six mandatory labels (decisions #9) plus the standard app labels. */}}
{{- define "product.labels" -}}
customer: {{ .Values.customer }}
environment: {{ .Values.environment }}
env-group: {{ .Values.envGroup }}
product: {{ .Values.product.shortCode }}
region-role: {{ .Values.regionRole }}
managed-by: argocd
{{ include "product.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/part-of: {{ .Values.product.name }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "product.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.product.shortCode }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "product.image" -}}
{{- $repo := printf "%s/%s" .Values.image.registry .Values.image.name -}}
{{- if .Values.image.digest -}}
{{ printf "%s@%s" $repo .Values.image.digest }}
{{- else -}}
{{ printf "%s:%s" $repo .Values.image.tag }}
{{- end -}}
{{- end -}}

{{/* Restricted Pod Security Standard for every container (architecture §10). */}}
{{- define "product.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
capabilities:
  drop: [ALL]
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Database connection settings shared by the app and the migration Job. */}}
{{- define "product.dbEnv" -}}
{{- if .Values.database.enabled }}
- { name: DB_HOST, value: "127.0.0.1" }
- { name: DB_PORT, value: {{ .Values.database.port | quote }} }
- { name: DB_NAME, value: {{ .Values.database.name | quote }} }
- { name: DB_SCHEMA, value: {{ .Values.database.schema | quote }} }
- { name: DB_USER, value: {{ .Values.database.user | quote }} }
{{- end }}
{{- end -}}

{{/* Cloud SQL Auth Proxy as a native sidecar: IAM login as the env GSA, private IP, write
     endpoint DNS name so a promoted DR replica is picked up without a config change. */}}
{{- define "product.sqlProxy" -}}
{{- if .Values.database.enabled }}
- name: cloud-sql-proxy
  image: {{ .Values.database.proxy.image }}
  restartPolicy: Always
  args:
    - --auto-iam-authn
    - --private-ip
    - --impersonate-service-account={{ .Values.database.impersonate }}
    - --port={{ .Values.database.port }}
    - --health-check
    - --http-address=0.0.0.0
    - --http-port=9801
    - --exit-zero-on-sigterm
    - --structured-logs
    - {{ .Values.database.endpoint }}
  startupProbe:
    httpGet: { path: /startup, port: 9801 }
    periodSeconds: 1
    failureThreshold: 60
  livenessProbe:
    httpGet: { path: /liveness, port: 9801 }
    periodSeconds: 10
  resources:
    requests:
      {{- toYaml .Values.database.proxy.resources | nindent 6 }}
    limits:
      memory: {{ .Values.database.proxy.resources.memory }}
  securityContext:
    {{- include "product.containerSecurity" . | nindent 4 }}
{{- end }}
{{- end -}}

{{- define "product.podSecurity" -}}
runAsNonRoot: true
runAsUser: {{ .Values.securityContext.runAsUser }}
runAsGroup: {{ .Values.securityContext.runAsGroup }}
fsGroup: {{ .Values.securityContext.fsGroup }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Pod template shared by the Rollout and the StatefulSet. */}}
{{- define "product.podTemplate" -}}
metadata:
  labels:
    {{- include "product.labels" . | nindent 4 }}
    {{- with .Values.podLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  annotations:
    checksum/config: {{ toYaml .Values.config | sha256sum }}
    proxy.istio.io/config: '{"holdApplicationUntilProxyStarts": true}'
    {{- with .Values.podAnnotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  serviceAccountName: {{ include "product.name" . }}
  automountServiceAccountToken: false
  terminationGracePeriodSeconds: {{ .Values.terminationGracePeriodSeconds }}
  securityContext:
    {{- include "product.podSecurity" . | nindent 4 }}
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          {{- include "product.selectorLabels" . | nindent 10 }}
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          {{- include "product.selectorLabels" . | nindent 10 }}
  {{- with (include "product.sqlProxy" .) }}
  initContainers:
    {{- . | trim | nindent 4 }}
  {{- end }}
  containers:
    - name: app
      image: {{ include "product.image" . }}
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      {{- with .Values.command }}
      command: {{ toJson . }}
      {{- end }}
      {{- with .Values.args }}
      args: {{ toJson . }}
      {{- end }}
      ports:
        - { name: http, containerPort: {{ .Values.port }}, protocol: TCP }
      env:
        - { name: CUSTOMER_ID, value: {{ .Values.customer | quote }} }
        - { name: ENVIRONMENT, value: {{ .Values.environment | quote }} }
        - { name: REGION_ROLE, value: {{ .Values.regionRole | quote }} }
        - { name: CONFIG_FILE, value: {{ printf "%s/config.yaml" .Values.configMountPath | quote }} }
        {{- with (include "product.dbEnv" . | trim) }}
        {{- . | nindent 8 }}
        {{- end }}
        {{- range $k, $v := .Values.platformEnv }}
        - { name: {{ $k }}, value: {{ $v | toString | quote }} }
        {{- end }}
        {{- range $k, $v := .Values.env }}
        {{- if not (hasKey $.Values.platformEnv $k) }}
        - { name: {{ $k }}, value: {{ $v | toString | quote }} }
        {{- end }}
        {{- end }}
      resources:
        requests:
          cpu: {{ .Values.resources.cpu | quote }}
          memory: {{ .Values.resources.memory }}
        limits:
          memory: {{ .Values.resources.memory }}
      startupProbe:
        httpGet: { path: {{ .Values.probes.readinessPath }}, port: http }
        periodSeconds: 2
        failureThreshold: {{ .Values.probes.startupFailureThreshold }}
      readinessProbe:
        httpGet: { path: {{ .Values.probes.readinessPath }}, port: http }
        periodSeconds: 5
      livenessProbe:
        httpGet: { path: {{ .Values.probes.livenessPath }}, port: http }
        periodSeconds: 10
        failureThreshold: 3
      lifecycle:
        preStop:
          sleep: { seconds: {{ .Values.preStopSleepSeconds }} }
      securityContext:
        {{- include "product.containerSecurity" . | nindent 8 }}
      volumeMounts:
        - { name: config, mountPath: {{ .Values.configMountPath }}, readOnly: true }
        - { name: tmp, mountPath: /tmp }
        {{- if .Values.persistence.enabled }}
        - { name: data, mountPath: {{ .Values.persistence.mountPath }} }
        {{- end }}
  volumes:
    - name: config
      configMap:
        name: {{ printf "%s-config" (include "product.name" .) }}
    - name: tmp
      emptyDir: { sizeLimit: 256Mi }
{{- end -}}

{{/* Route destinations: stable, plus the canary Service at weight 0 (Argo Rollouts sets the weights). */}}
{{- define "product.routeDestinations" -}}
{{- $ := .root -}}
- destination:
    host: {{ include "product.host" $ }}
    port: { number: {{ $.Values.port }} }
  weight: 100
{{- if eq .strategy "canary" }}
- destination:
    host: {{ printf "%s-canary.%s.svc.cluster.local" (include "product.name" $) (include "product.namespace" $) }}
    port: { number: {{ $.Values.port }} }
  weight: 0
{{- end }}
{{- end -}}
