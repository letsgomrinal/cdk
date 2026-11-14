# Cloud Run function (formerly Cloud Functions gen2): a Cloud Run service running
# a Functions Framework container (built from the component's Dockerfile like any
# other component), plus Eventarc triggers that deliver events to it.
#
# The trigger runs as the function's own SA. That SA gets:
#   - roles/run.invoker on this function only
#   - roles/eventarc.eventReceiver on the project. Eventarc has no narrower scope;
#     it's only granted when the function has triggers.

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = ">= 8.0" }
  }
}

variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "labels" { type = map(string) }
variable "service_account_email" { type = string }

variable "env" {
  type    = map(string)
  default = {}
}

variable "secret_env" {
  type    = map(string)
  default = {}
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type    = number
  default = 10
}

variable "concurrency" {
  type    = number
  default = 1
}

variable "timeout" {
  type    = string
  default = "300s"
}

variable "ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_INTERNAL_ONLY"
}

variable "vpc" {
  type = object({
    network    = string
    subnetwork = string
    egress     = optional(string, "PRIVATE_RANGES_ONLY")
  })
  default = null
}

variable "triggers" {
  description = <<-EOT
    Trigger name => Eventarc trigger spec. Examples:
      gcs    = { event_type = "google.cloud.storage.object.v1.finalized", filters = { bucket = "my-bucket" } }
      pubsub = { event_type = "google.cloud.pubsub.topic.v1.messagePublished", pubsub_topic = "projects/p/topics/t" }
  EOT
  type = map(object({
    event_type   = string
    filters      = optional(map(string), {})
    pubsub_topic = optional(string)
    path         = optional(string)
  }))
  default = {}
}

variable "deletion_protection" {
  type    = bool
  default = true
}

module "service" {
  source = "../cloud-run-service"

  project_id            = var.project_id
  region                = var.region
  name                  = var.name
  labels                = var.labels
  service_account_email = var.service_account_email
  env                   = var.env
  secret_env            = var.secret_env
  cpu                   = var.cpu
  memory                = var.memory
  min_instances         = var.min_instances
  max_instances         = var.max_instances
  concurrency           = var.concurrency
  timeout               = var.timeout
  ingress               = var.ingress
  vpc                   = var.vpc
  deletion_protection   = var.deletion_protection
}

resource "google_cloud_run_v2_service_iam_member" "trigger_invoker" {
  count    = length(var.triggers) > 0 ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = module.service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.service_account_email}"
}

resource "google_project_iam_member" "event_receiver" {
  count   = length(var.triggers) > 0 ? 1 : 0
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${var.service_account_email}"
}

resource "google_eventarc_trigger" "this" {
  for_each        = var.triggers
  project         = var.project_id
  location        = var.region
  name            = "${var.name}-${each.key}"
  labels          = var.labels
  service_account = var.service_account_email

  matching_criteria {
    attribute = "type"
    value     = each.value.event_type
  }

  dynamic "matching_criteria" {
    for_each = each.value.filters
    content {
      attribute = matching_criteria.key
      value     = matching_criteria.value
    }
  }

  dynamic "transport" {
    for_each = each.value.pubsub_topic == null ? [] : [each.value.pubsub_topic]
    content {
      pubsub {
        topic = transport.value
      }
    }
  }

  destination {
    cloud_run_service {
      service = module.service.name
      region  = var.region
      path    = each.value.path
    }
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.trigger_invoker,
    google_project_iam_member.event_receiver,
  ]
}

output "name" {
  value = module.service.name
}

output "id" {
  value = module.service.id
}

output "uri" {
  value = module.service.uri
}
