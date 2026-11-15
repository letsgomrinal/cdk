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
  description = "The env's network for Direct VPC egress (from platform.yaml). Each workload picks its egress mode, or NONE."
  type = object({
    network    = string
    subnetwork = string
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
# Workloads by type. Usually produced by `cdk sync` from each component's
# deployment.yml; the shared fields are repeated per type because Terraform
# has no type inheritance. See the field comments in `services`.
# ------------------------------------------------------------------------

variable "services" {
  description = "Cloud Run services (apps, apis)."
  type = map(object({
    image      = optional(string)
    command    = optional(list(string))
    args       = optional(list(string))
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    egress     = optional(string, "PRIVATE_RANGES_ONLY") # PRIVATE_RANGES_ONLY | ALL_TRAFFIC | NONE (no VPC)
    calls      = optional(list(string), [])              # "service/backend": invoker grant + BACKEND_URL env
    access = optional(object({
      secrets           = optional(list(string), [])
      buckets           = optional(map(string), {})
      publish           = optional(list(string), [])
      subscribe         = optional(list(string), [])
      bigquery_datasets = optional(map(string), {})
      project_roles     = optional(list(string), [])
    }), {})

    port                  = optional(number, 8080)
    ingress               = optional(string, "INGRESS_TRAFFIC_INTERNAL_ONLY")
    min_instances         = optional(number, 0)
    max_instances         = optional(number, 10)
    concurrency           = optional(number, 80)
    timeout               = optional(string, "300s")
    cpu_idle              = optional(bool, true)  # CPU only while handling requests
    startup_cpu_boost     = optional(bool, false) # extra CPU while starting
    session_affinity      = optional(bool, false)
    execution_environment = optional(string) # EXECUTION_ENVIRONMENT_GEN1 | _GEN2
    startup_probe = optional(object({
      http_path             = optional(string) # null = TCP check
      port                  = optional(number) # default: the container port (8080 for worker pools)
      initial_delay_seconds = optional(number, 0)
      period_seconds        = optional(number, 10)
      timeout_seconds       = optional(number, 1)
      failure_threshold     = optional(number, 3)
    }))
    liveness_probe = optional(object({
      http_path             = optional(string) # null = TCP check
      port                  = optional(number) # default: the container port (8080 for worker pools)
      initial_delay_seconds = optional(number, 0)
      period_seconds        = optional(number, 10)
      timeout_seconds       = optional(number, 1)
      failure_threshold     = optional(number, 3)
    }))
    invokers = optional(list(string), []) # "job/reconcile" or IAM members
  }))
  default = {}
  validation {
    condition     = alltrue([for k in keys(var.services) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "services keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  validation {
    condition     = alltrue([for w in values(var.services) : contains(["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC", "NONE"], w.egress)])
    error_message = "egress must be PRIVATE_RANGES_ONLY, ALL_TRAFFIC or NONE."
  }
}

variable "jobs" {
  description = "Cloud Run jobs."
  type = map(object({
    image      = optional(string)
    command    = optional(list(string))
    args       = optional(list(string))
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    egress     = optional(string, "PRIVATE_RANGES_ONLY") # PRIVATE_RANGES_ONLY | ALL_TRAFFIC | NONE (no VPC)
    calls      = optional(list(string), [])              # "service/backend": invoker grant + BACKEND_URL env
    access = optional(object({
      secrets           = optional(list(string), [])
      buckets           = optional(map(string), {})
      publish           = optional(list(string), [])
      subscribe         = optional(list(string), [])
      bigquery_datasets = optional(map(string), {})
      project_roles     = optional(list(string), [])
    }), {})

    task_count            = optional(number, 1)
    parallelism           = optional(number, 0) # 0 = run all tasks at once
    max_retries           = optional(number, 3)
    timeout               = optional(string, "600s") # per task
    execution_environment = optional(string)
    schedules = optional(map(object({
      cron      = string
      time_zone = optional(string, "Etc/UTC")
      args      = optional(list(string))
      paused    = optional(bool, false)
    })), {})
  }))
  default = {}
  validation {
    condition     = alltrue([for k in keys(var.jobs) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "jobs keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  validation {
    condition     = alltrue([for w in values(var.jobs) : contains(["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC", "NONE"], w.egress)])
    error_message = "egress must be PRIVATE_RANGES_ONLY, ALL_TRAFFIC or NONE."
  }
}

variable "worker_pools" {
  description = "Cloud Run worker pools."
  type = map(object({
    image      = optional(string)
    command    = optional(list(string))
    args       = optional(list(string))
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    egress     = optional(string, "PRIVATE_RANGES_ONLY") # PRIVATE_RANGES_ONLY | ALL_TRAFFIC | NONE (no VPC)
    calls      = optional(list(string), [])              # "service/backend": invoker grant + BACKEND_URL env
    access = optional(object({
      secrets           = optional(list(string), [])
      buckets           = optional(map(string), {})
      publish           = optional(list(string), [])
      subscribe         = optional(list(string), [])
      bigquery_datasets = optional(map(string), {})
      project_roles     = optional(list(string), [])
    }), {})

    instances = optional(number, 1)
    startup_probe = optional(object({
      http_path             = optional(string) # null = TCP check
      port                  = optional(number) # default: the container port (8080 for worker pools)
      initial_delay_seconds = optional(number, 0)
      period_seconds        = optional(number, 10)
      timeout_seconds       = optional(number, 1)
      failure_threshold     = optional(number, 3)
    }))
    liveness_probe = optional(object({
      http_path             = optional(string) # null = TCP check
      port                  = optional(number) # default: the container port (8080 for worker pools)
      initial_delay_seconds = optional(number, 0)
      period_seconds        = optional(number, 10)
      timeout_seconds       = optional(number, 1)
      failure_threshold     = optional(number, 3)
    }))
  }))
  default = {}
  validation {
    condition     = alltrue([for k in keys(var.worker_pools) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "worker_pools keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  validation {
    condition     = alltrue([for w in values(var.worker_pools) : contains(["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC", "NONE"], w.egress)])
    error_message = "egress must be PRIVATE_RANGES_ONLY, ALL_TRAFFIC or NONE."
  }
}

variable "functions" {
  description = "Cloud Run functions (Functions Framework container + Eventarc triggers)."
  type = map(object({
    image      = optional(string)
    command    = optional(list(string))
    args       = optional(list(string))
    env        = optional(map(string), {})
    secret_env = optional(map(string), {})
    cpu        = optional(string, "1")
    memory     = optional(string, "512Mi")
    egress     = optional(string, "PRIVATE_RANGES_ONLY") # PRIVATE_RANGES_ONLY | ALL_TRAFFIC | NONE (no VPC)
    calls      = optional(list(string), [])              # "service/backend": invoker grant + BACKEND_URL env
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
  validation {
    condition     = alltrue([for k in keys(var.functions) : can(regex("^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$", k))])
    error_message = "functions keys must be 1-15 chars, lowercase letters/digits/hyphens, starting with a letter, not ending with a hyphen."
  }
  validation {
    condition     = alltrue([for w in values(var.functions) : contains(["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC", "NONE"], w.egress)])
    error_message = "egress must be PRIVATE_RANGES_ONLY, ALL_TRAFFIC or NONE."
  }
}
