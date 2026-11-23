output "project_id" {
  value = google_project.this.project_id
}

output "number" {
  value = google_project.this.number
}

output "audit_sink_writer" {
  value = try(google_logging_project_sink.audit[0].writer_identity, null)
}
