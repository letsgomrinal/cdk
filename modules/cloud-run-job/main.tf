# Cloud Run job, with optional Cloud Scheduler triggers.
# Scheduler calls the job's :run endpoint as the job's own SA, which gets
# roles/run.invoker on this job only.

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

variable "image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/job"
}

variable "command" {
  type    = list(string)
  default = null
}

variable "args" {
  type    = list(string)
  default = null
}

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

variable "task_count" {
  type    = number
  default = 1
}

variable "parallelism" {
  type    = number
  default = 1
}

variable "max_retries" {
  type    = number
  default = 1
}

variable "timeout" {
  description = "Per-task timeout."
  type        = string
  default     = "600s"
}

variable "vpc" {
  type = object({
    network    = string
    subnetwork = string
    egress     = optional(string, "PRIVATE_RANGES_ONLY")
  })
  default = null
}

variable "schedules" {
  description = "Schedule name => { cron, time_zone, args }. args overrides the container args for that schedule."
  type = map(object({
    cron      = string
    time_zone = optional(string, "Etc/UTC")
    args      = optional(list(string))
    paused    = optional(bool, false)
  }))
  default = {}
}

variable "deletion_protection" {
  type    = bool
  default = true
}

locals {
  secret_env = {
    for k, v in var.secret_env : k => {
      secret  = split(":", v)[0]
      version = length(split(":", v)) > 1 ? split(":", v)[1] : "latest"
    }
  }
}

resource "google_cloud_run_v2_job" "this" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  labels              = var.labels
  deletion_protection = var.deletion_protection

  template {
    labels      = var.labels
    task_count  = var.task_count
    parallelism = var.parallelism

    template {
      service_account = var.service_account_email
      max_retries     = var.max_retries
      timeout         = var.timeout

      dynamic "vpc_access" {
        for_each = var.vpc == null ? [] : [var.vpc]
        content {
          egress = vpc_access.value.egress
          network_interfaces {
            network    = vpc_access.value.network
            subnetwork = vpc_access.value.subnetwork
          }
        }
      }

      containers {
        image   = var.image
        command = var.command
        args    = var.args

        resources {
          limits = { cpu = var.cpu, memory = var.memory }
        }

        dynamic "env" {
          for_each = var.env
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = local.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value.secret
                version = env.value.version
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  count    = length(var.schedules) > 0 ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.this.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_scheduler_job" "this" {
  for_each  = var.schedules
  project   = var.project_id
  region    = var.region
  name      = "${var.name}-${each.key}"
  schedule  = each.value.cron
  time_zone = each.value.time_zone
  paused    = each.value.paused

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.this.id}:run"
    body = each.value.args == null ? null : base64encode(jsonencode({
      overrides = { containerOverrides = [{ args = each.value.args }] }
    }))
    headers = each.value.args == null ? null : { "Content-Type" = "application/json" }

    oauth_token {
      service_account_email = var.service_account_email
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_invoker]
}

output "name" {
  value = google_cloud_run_v2_job.this.name
}

output "id" {
  value = google_cloud_run_v2_job.this.id
}
