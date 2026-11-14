# Cloud Run service (HTTP). Also used for functions; see modules/cloud-function.
#
# Who owns what: Terraform/Atlantis owns configuration (env, scaling, IAM,
# networking). Drone owns the image and rolls out releases with
# `gcloud run deploy`. That's why the container image is in ignore_changes.

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
  description = "Only used at creation. Releases change the image after that."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
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
  description = "ENV_VAR => \"secret-id\" or \"secret-id:version\" (version defaults to latest)."
  type        = map(string)
  default     = {}
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "port" {
  type    = number
  default = 8080
}

variable "ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  validation {
    condition = contains([
      "INGRESS_TRAFFIC_ALL",
      "INGRESS_TRAFFIC_INTERNAL_ONLY",
      "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER",
    ], var.ingress)
    error_message = "Invalid ingress."
  }
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
  default = 80
}

variable "timeout" {
  type    = string
  default = "300s"
}

variable "cpu_idle" {
  description = "true = CPU only allocated during requests."
  type        = bool
  default     = true
}

variable "vpc" {
  description = "Direct VPC egress. null = no VPC."
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

resource "google_cloud_run_v2_service" "this" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  labels              = var.labels
  ingress             = var.ingress
  deletion_protection = var.deletion_protection

  template {
    service_account                  = var.service_account_email
    labels                           = var.labels
    timeout                          = var.timeout
    max_instance_request_concurrency = var.concurrency

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

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

      ports {
        container_port = var.port
      }

      resources {
        limits   = { cpu = var.cpu, memory = var.memory }
        cpu_idle = var.cpu_idle
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
      client,
      client_version,
      build_config,
    ]
  }
}

output "name" {
  value = google_cloud_run_v2_service.this.name
}

output "id" {
  value = google_cloud_run_v2_service.this.id
}

output "uri" {
  value = google_cloud_run_v2_service.this.uri
}
