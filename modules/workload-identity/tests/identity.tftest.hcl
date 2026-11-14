mock_provider "google" {}

variables {
  project_id   = "acme-orders-dev"
  account_id   = "orders-export-job"
  display_name = "orders / export (job)"
}

run "resource_level_grants" {
  command = plan
  variables {
    access = {
      secrets           = ["db-url", "projects/shared/secrets/api-key"]
      buckets           = { exports = "write", templates = "read" }
      bigquery_datasets = { "analytics" = "write", "other-proj:raw" = "read" }
    }
  }
  assert {
    condition     = google_storage_bucket_iam_member.buckets["exports"].role == "roles/storage.objectUser"
    error_message = "write should map to objectUser."
  }
  assert {
    condition     = google_bigquery_dataset_iam_member.datasets["other-proj:raw"].project == "other-proj"
    error_message = "project:dataset form should target the other project."
  }
  assert {
    condition     = length(google_secret_manager_secret_iam_member.secrets) == 2
    error_message = "One accessor grant per secret."
  }
}

run "rejects_basic_roles" {
  command = plan
  variables {
    access = { project_roles = ["roles/editor"] }
  }
  expect_failures = [var.access]
}

run "rejects_unknown_bucket_mode" {
  command = plan
  variables {
    access = { buckets = { b = "owner" } }
  }
  expect_failures = [var.access]
}
