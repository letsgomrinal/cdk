# One dedicated service account per workload, plus resource-level IAM grants.
#
# Every grant is an additive *_iam_member on the narrowest resource GCP offers
# (one secret, one bucket, one topic...). Nothing here uses *_iam_binding or
# *_iam_policy, so we never overwrite grants managed elsewhere.

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = ">= 8.0" }
  }
}

variable "project_id" { type = string }
variable "account_id" { type = string }
variable "display_name" { type = string }
variable "description" {
  type    = string
  default = ""
}

variable "access" {
  description = "Resources this workload may use. See docs/IAM.md."
  type = object({
    # Secret IDs ("db-url") or full names ("projects/p/secrets/db-url") -> roles/secretmanager.secretAccessor
    secrets = optional(list(string), [])
    # bucket name => "read" | "write" | "admin"
    buckets = optional(map(string), {})
    # Pub/Sub topic names or full IDs -> roles/pubsub.publisher
    publish = optional(list(string), [])
    # Pub/Sub subscription names or full IDs -> roles/pubsub.subscriber
    subscribe = optional(list(string), [])
    # "project:dataset" or "dataset" => "read" | "write"
    bigquery_datasets = optional(map(string), {})
    # Escape hatch. Project-wide roles need a reason in code review; prefer the typed grants above.
    project_roles = optional(list(string), [])
  })
  default = {}

  validation {
    condition     = alltrue([for m in values(var.access.buckets) : contains(["read", "write", "admin"], m)])
    error_message = "access.buckets values must be read, write or admin."
  }
  validation {
    condition     = alltrue([for m in values(var.access.bigquery_datasets) : contains(["read", "write"], m)])
    error_message = "access.bigquery_datasets values must be read or write."
  }
  validation {
    condition = alltrue([for r in var.access.project_roles : !contains([
      "roles/owner", "roles/editor", "roles/viewer",
      "roles/iam.serviceAccountTokenCreator", "roles/iam.serviceAccountUser",
      "roles/resourcemanager.projectIamAdmin",
    ], r)])
    error_message = "access.project_roles must not contain basic roles or roles that allow impersonation / IAM changes."
  }
}

variable "deployers" {
  description = "Principals (e.g. the Drone release SA) allowed to deploy revisions that run as this SA."
  type        = list(string)
  default     = []
}

locals {
  bucket_roles = {
    read  = "roles/storage.objectViewer"
    write = "roles/storage.objectUser"
    admin = "roles/storage.objectAdmin"
  }
  bq_roles = {
    read  = "roles/bigquery.dataViewer"
    write = "roles/bigquery.dataEditor"
  }
  member = "serviceAccount:${google_service_account.this.email}"

  bq = {
    for k, mode in var.access.bigquery_datasets : k => {
      project = length(split(":", k)) == 2 ? split(":", k)[0] : var.project_id
      dataset = length(split(":", k)) == 2 ? split(":", k)[1] : k
      role    = local.bq_roles[mode]
    }
  }
}

resource "google_service_account" "this" {
  project      = var.project_id
  account_id   = var.account_id
  display_name = var.display_name
  description  = var.description
}

resource "google_secret_manager_secret_iam_member" "secrets" {
  for_each  = toset(var.access.secrets)
  project   = startswith(each.value, "projects/") ? null : var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = local.member
}

resource "google_storage_bucket_iam_member" "buckets" {
  for_each = var.access.buckets
  bucket   = each.key
  role     = local.bucket_roles[each.value]
  member   = local.member
}

resource "google_pubsub_topic_iam_member" "publish" {
  for_each = toset(var.access.publish)
  project  = startswith(each.value, "projects/") ? null : var.project_id
  topic    = each.value
  role     = "roles/pubsub.publisher"
  member   = local.member
}

resource "google_pubsub_subscription_iam_member" "subscribe" {
  for_each     = toset(var.access.subscribe)
  project      = startswith(each.value, "projects/") ? null : var.project_id
  subscription = each.value
  role         = "roles/pubsub.subscriber"
  member       = local.member
}

resource "google_bigquery_dataset_iam_member" "datasets" {
  for_each   = local.bq
  project    = each.value.project
  dataset_id = each.value.dataset
  role       = each.value.role
  member     = local.member
}

resource "google_project_iam_member" "project" {
  for_each = toset(var.access.project_roles)
  project  = var.project_id
  role     = each.value
  member   = local.member
}

# Deployers may "act as" this SA only, not every SA in the project.
resource "google_service_account_iam_member" "deployers" {
  for_each           = toset(var.deployers)
  service_account_id = google_service_account.this.name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value
}

output "email" {
  value = google_service_account.this.email
}

output "member" {
  value = local.member
}

output "id" {
  value = google_service_account.this.id
}
