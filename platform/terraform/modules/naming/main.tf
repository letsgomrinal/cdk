# Pure naming module: no resources, only computed names and labels.
# Every other module derives names from here so the convention lives in one place.
#
#   resource name / SA id : {product}-{workload}-{type_code}     e.g. orders-nightly-export-job
#   SA email              : {resource name}@{project}.iam.gserviceaccount.com
#
# Limits: product <= 10, workload <= 15, type_code <= 3  =>  <= 30 chars,
# which is the hard limit for service account IDs. Cloud Run names allow 49.

terraform {
  required_version = ">= 1.6"
}

variable "product" {
  description = "Product short code (2-10 chars, lowercase letters/digits, starts with a letter, no hyphens)."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.product))
    error_message = "product must match ^[a-z][a-z0-9]{1,9}$ (2-10 chars, no hyphens)."
  }
}

variable "workload" {
  description = "Workload name within the product (1-15 chars, lowercase letters/digits/hyphens)."
  type        = string
  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", var.workload))
    error_message = "workload must match ^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$ (1-15 chars, no leading/trailing hyphen)."
  }
}

variable "type" {
  description = "Workload type."
  type        = string
  validation {
    condition     = contains(["service", "job", "worker-pool", "function"], var.type)
    error_message = "type must be one of: service, job, worker-pool, function."
  }
}

variable "env" {
  description = "Environment (dev, staging, prod, ...). Used in labels only; environments are separated by project."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.env))
    error_message = "env must match ^[a-z][a-z0-9]{1,9}$."
  }
}

variable "project_id" {
  type = string
}

variable "team" {
  description = "Owning team, used as a label."
  type        = string
}

variable "extra_labels" {
  type    = map(string)
  default = {}
}

locals {
  type_codes = {
    service       = "svc"
    job           = "job"
    "worker-pool" = "wp"
    function      = "fn"
  }
  type_code = local.type_codes[var.type]
  name      = "${var.product}-${var.workload}-${local.type_code}"
}

output "name" {
  description = "Name for the Cloud Run resource and the service account ID."
  value       = local.name
}

output "type_code" {
  value = local.type_code
}

output "service_account_id" {
  value = local.name
}

output "service_account_email" {
  value = "${local.name}@${var.project_id}.iam.gserviceaccount.com"
}

output "service_account_display_name" {
  value = "${var.product} / ${var.workload} (${var.type})"
}

output "labels" {
  description = "Labels on every resource the kit creates. The standard ones always win."
  value = merge(var.extra_labels, {
    product       = var.product
    workload      = var.workload
    workload-type = var.type
    env           = var.env
    team          = var.team
    managed-by    = "terraform"
  })
}
