{{- define "office-wallet.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "office-wallet.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "office-wallet.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "office-wallet.labels" -}}
app.kubernetes.io/name: {{ include "office-wallet.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "office-wallet.selectorLabels" -}}
app.kubernetes.io/name: {{ include "office-wallet.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "office-wallet.mailHost" -}}
{{- if .Values.app.mailHost -}}
{{- .Values.app.mailHost -}}
{{- else if .Values.mail.enabled -}}
{{- printf "%s-mail" (include "office-wallet.fullname" .) -}}
{{- else -}}
mail
{{- end -}}
{{- end -}}

{{- define "office-wallet.mockHost" -}}
{{- printf "%s-mock" (include "office-wallet.fullname" .) -}}
{{- end -}}
