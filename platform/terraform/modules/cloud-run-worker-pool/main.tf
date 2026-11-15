# Cloud Run worker pool: always-on, pull-based workers (Pub/Sub pull, Kafka,
# queue consumers). No HTTP endpoint, so there's no ingress or invoker.

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
  default = "us-docker.pkg.dev/cloudrun/container/hello"
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

variable "instances" {
  description = "Manual instance count."
  type        = number
  default     = 1
}


variable "startup_probe" {
  description = "null = no probe. http_path null = TCP check."
  type = object({
    http_path             = optional(string)
    port                  = optional(number)
    initial_delay_seconds = optional(number, 0)
    period_seconds        = optional(number, 10)
    timeout_seconds       = optional(number, 1)
    failure_threshold     = optional(number, 3)
  })
  default = null
}

variable "liveness_probe" {
  description = "null = no probe. http_path null = TCP check."
  type = object({
    http_path             = optional(string)
    port                  = optional(number)
    initial_delay_seconds = optional(number, 0)
    period_seconds        = optional(number, 10)
    timeout_seconds       = optional(number, 1)
    failure_threshold     = optional(number, 3)
  })
  default = null
}

variable "vpc" {
  type = object({
    network    = string
    subnetwork = string
    egress     = optional(string, "PRIVATE_RANGES_ONLY")
  })
  default = null
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

resource "google_cloud_run_v2_worker_pool" "this" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  labels              = var.labels
  deletion_protection = var.deletion_protection

  scaling {
    scaling_mode          = "MANUAL"
    manual_instance_count = var.instances
  }

  template {
    service_account = var.service_account_email
    labels          = var.labels

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

      dynamic "startup_probe" {
        for_each = var.startup_probe == null ? [] : [var.startup_probe]
        content {
          initial_delay_seconds = startup_probe.value.initial_delay_seconds
          period_seconds        = startup_probe.value.period_seconds
          timeout_seconds       = startup_probe.value.timeout_seconds
          failure_threshold     = startup_probe.value.failure_threshold
          dynamic "http_get" {
            for_each = startup_probe.value.http_path == null ? [] : [startup_probe.value.http_path]
            content {
              path = http_get.value
              port = coalesce(startup_probe.value.port, 8080)
            }
          }
          dynamic "tcp_socket" {
            for_each = startup_probe.value.http_path == null ? [1] : []
            content { port = coalesce(startup_probe.value.port, 8080) }
          }
        }
      }

      dynamic "liveness_probe" {
        for_each = var.liveness_probe == null ? [] : [var.liveness_probe]
        content {
          initial_delay_seconds = liveness_probe.value.initial_delay_seconds
          period_seconds        = liveness_probe.value.period_seconds
          timeout_seconds       = liveness_probe.value.timeout_seconds
          failure_threshold     = liveness_probe.value.failure_threshold
          dynamic "http_get" {
            for_each = liveness_probe.value.http_path == null ? [] : [liveness_probe.value.http_path]
            content {
              path = http_get.value
              port = coalesce(liveness_probe.value.port, 8080)
            }
          }
          dynamic "tcp_socket" {
            for_each = liveness_probe.value.http_path == null ? [1] : []
            content { port = coalesce(liveness_probe.value.port, 8080) }
          }
        }
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

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      instance_splits,
      client,
      client_version,
    ]
  }
}

output "name" {
  value = google_cloud_run_v2_worker_pool.this.name
}

output "id" {
  value = google_cloud_run_v2_worker_pool.this.id
}
