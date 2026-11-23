{{- define "mesh.labels" -}}
customer: shared
environment: shared
env-group: {{ .Values.group }}
product: platform
region-role: {{ .Values.regionRole }}
managed-by: argocd
{{- end -}}

{{/* An Istio gateway Deployment + Service + HPA + PDB. Call with (dict "root" $ "name" ... "cfg" ...). */}}
{{- define "mesh.gateway" -}}
{{- $ := .root -}}
{{- $sel := dict "istio" .name -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .name }}
  namespace: {{ .cfg.namespace }}
  labels:
    {{- include "mesh.labels" $ | nindent 4 }}
automountServiceAccountToken: false
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .name }}
  namespace: {{ .cfg.namespace }}
  labels:
    {{- include "mesh.labels" $ | nindent 4 }}
spec:
  selector:
    matchLabels:
      {{- toYaml $sel | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "mesh.labels" $ | nindent 8 }}
        {{- toYaml $sel | nindent 8 }}
        sidecar.istio.io/inject: "true"
      annotations:
        inject.istio.io/templates: gateway     # managed Istio replaces "auto" with the gateway proxy
    spec:
      serviceAccountName: {{ .name }}
      securityContext:
        runAsNonRoot: true
        runAsUser: 1337
        runAsGroup: 1337
        seccompProfile: { type: RuntimeDefault }
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              {{- toYaml $sel | nindent 14 }}
      containers:
        - name: istio-proxy
          image: auto
          ports:
            - { name: https, containerPort: 8443, protocol: TCP }
            - { name: status, containerPort: 15021, protocol: TCP }
          resources:
            requests:
              {{- toYaml .cfg.resources | nindent 14 }}
            limits:
              memory: {{ .cfg.resources.memory }}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            capabilities: { drop: [ALL] }
            seccompProfile: { type: RuntimeDefault }
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ .name }}
  namespace: {{ .cfg.namespace }}
  labels:
    {{- include "mesh.labels" $ | nindent 4 }}
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: {{ .name }} }
  minReplicas: {{ .cfg.replicas.min }}
  maxReplicas: {{ .cfg.replicas.max }}
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 60 } }
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ .name }}
  namespace: {{ .cfg.namespace }}
  labels:
    {{- include "mesh.labels" $ | nindent 4 }}
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      {{- toYaml $sel | nindent 6 }}
{{- end -}}
