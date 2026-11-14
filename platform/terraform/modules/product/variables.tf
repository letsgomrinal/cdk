variable "product" {
  description = "Product short code, 2-10 chars, [a-z][a-z0-9]*. Prefix of every resource and SA name."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.product))
    error_message = "product must be 2-10 chars, lowercase letters/digits, starting with a letter, no hyphens (SA IDs are capped at 30 chars)."
  }
}

variable "env" {
  type = string
}

variable "team" {
  type = string
}

variable "project_id" {
  description = "GCP project for this product+env. One environment per project is required (SA names don't include env)."
  type        = string
}

variable "region" {
  type = string
}

variable "labels" {
  description = "Extra labels for every resource (e.g. cost-center)."
  type        = map(string)
  default     = {}
}

variable "vpc" {
  description = "Default Direct VPC egress for all workloads (a workload can opt out with use_vpc = false). Comes from the foundation layer."
  type = object({
    network    = string
    subnetwork = string
    egress     = optional(string, "PRIVATE_RANGES_ONLY")
  })
  default = null
}

variable "deployers" {
  description = "Principals that roll out releases (Drone). They get run.developer on each resource and serviceAccountUser on each runtime SA."
  type        = list(string)
  default     = []
}

variable "deletion_protection" {
  type    = bool
  default = true
}

# ------------------------------------------------------------------------
# Shared by every workload type (repeated in each object below, because
# Terraform has no type inheritance):
#
#   image      : first image only; Drone owns the image after creation
#   command, args, env, cpu, memory
#   secret_env : ENV => "secret-id[:version]"; access is granted automatically
#   access     : resource-level grants for this workload's SA (docs/IAM.md)
#   use_vpc    : attach the product's VPC (default true)
# ------------------------------------------------------------------------

variable "services" {
  description = "Workload name => spec. Names: 1-15 chars, [a-z][a-z0-9-]*, no trailing hyphen."
  validation {
    condition     = alltrue([for k in keys(var.services) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "services keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  type = map(object({
    image      = optional(string)
    command    = optional(list(string))
    args       = optional(list(string))
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    use_vpc    = optional(bool, true)
    access = optional(object({
      secrets           = optional(list(string), [])
      buckets           = optional(map(string), {})
      publish           = optional(list(string), [])
      subscribe         = optional(list(string), [])
      bigquery_datasets = optional(map(string), {})
      project_roles     = optional(list(string), [])
    }), {})

    port          = optional(number, 8080)
    ingress       = optional(string, "INGRESS_TRAFFIC_INTERNAL_ONLY")
    min_instances = optional(number, 0)
    max_instances = optional(number, 10)
    concurrency   = optional(number, 80)
    timeout       = optional(string, "300s")
    cpu_idle      = optional(bool, true)
    # Who may call this service: "job/reconcile" (same product) or IAM members.
    invokers = optional(list(string), [])
  }))
  default = {}
}

variable "jobs" {
  description = "Workload name => spec. Names: 1-15 chars, [a-z][a-z0-9-]*, no trailing hyphen."
  validation {
    condition     = alltrue([for k in keys(var.jobs) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "jobs keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  type = map(object({
    image      = optional(string)
    command    = optional(list(string))
    args       = optional(list(string))
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    use_vpc    = optional(bool, true)
    access = optional(object({
      secrets           = optional(list(string), [])
      buckets           = optional(map(string), {})
      publish           = optional(list(string), [])
      subscribe         = optional(list(string), [])
      bigquery_datasets = optional(map(string), {})
      project_roles     = optional(list(string), [])
    }), {})

    task_count  = optional(number, 1)
    parallelism = optional(number, 1)
    max_retries = optional(number, 1)
    timeout     = optional(string, "600s")
    schedules = optional(map(object({
      cron      = string
      time_zone = optional(string, "Etc/UTC")
      args      = optional(list(string))
      paused    = optional(bool, false)
    })), {})
  }))
  default = {}
}

variable "worker_pools" {
  description = "Workload name => spec. Names: 1-15 chars, [a-z][a-z0-9-]*, no trailing hyphen."
  validation {
    condition     = alltrue([for k in keys(var.worker_pools) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "worker_pools keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  type = map(object({
    image      = optional(string)
    command    = optional(list(string))
    args       = optional(list(string))
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    use_vpc    = optional(bool, true)
    access = optional(object({
      secrets           = optional(list(string), [])
      buckets           = optional(map(string), {})
      publish           = optional(list(string), [])
      subscribe         = optional(list(string), [])
      bigquery_datasets = optional(map(string), {})
      project_roles     = optional(list(string), [])
    }), {})

    instances = optional(number, 1)
  }))
  default = {}
}

variable "functions" {
  description = "Workload name => spec. Names: 1-15 chars, [a-z][a-z0-9-]*, no trailing hyphen."
  validation {
    condition     = alltrue([for k in keys(var.functions) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "functions keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  type = map(object({
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    use_vpc    = optional(bool, true)
    access = optional(object({
      secrets           = optional(list(string), [])
      buckets           = optional(map(string), {})
      publish           = optional(list(string), [])
      subscribe         = optional(list(string), [])
      bigquery_datasets = optional(map(string), {})
      project_roles     = optional(list(string), [])
    }), {})

    ingress       = optional(string, "INGRESS_TRAFFIC_INTERNAL_ONLY")
    min_instances = optional(number, 0)
    max_instances = optional(number, 10)
    concurrency   = optional(number, 1)
    timeout       = optional(string, "300s")
    invokers      = optional(list(string), [])
    triggers = optional(map(object({
      event_type   = string
      filters      = optional(map(string), {})
      pubsub_topic = optional(string)
      path         = optional(string)
    })), {})
  }))
  default = {}
}
