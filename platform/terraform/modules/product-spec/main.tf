# Turns a product.yaml (plus the repo-wide platform.yaml) into a call to
# modules/product. This is where the user-facing component kinds map to Cloud Run types:
#
#   kind      -> type          notes
#   web       -> service       React / Next.js frontends; `public: true` opens it to the internet
#   api       -> service       FastAPI etc.; internal by default
#   job       -> job
#   worker    -> worker-pool
#   function  -> function      Eventarc-triggered
#
# product.yaml extras handled here:
#   calls: [backend]   -> caller gets run.invoker on backend, plus env BACKEND_URL
#   public: true       -> ingress ALL + allUsers invoker (web/api/function only)
#   overrides.<env>    -> per-env, per-component shallow merge (e.g. prod sizing)
#   "{env}", "{project}", "{product}" placeholders anywhere in component config
#   every workload gets env ENV, PRODUCT, COMPONENT

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = ">= 8.0" }
  }
}

variable "spec" {
  description = "yamldecode(product.yaml)"
  type        = any
}

variable "platform" {
  description = "yamldecode(platform.yaml)"
  type        = any
}

variable "env" {
  type = string
}

locals {
  kinds = {
    web      = "service"
    api      = "service"
    job      = "job"
    worker   = "worker-pool"
    function = "function"
  }
  codes = { service = "svc", job = "job", "worker-pool" = "wp", function = "fn" }

  common_keys = ["kind", "template", "env", "secret_env", "cpu", "memory", "use_vpc", "access", "calls"]
  allowed_keys = {
    service       = concat(local.common_keys, ["image", "command", "args", "public", "port", "ingress", "min_instances", "max_instances", "concurrency", "timeout", "cpu_idle", "invokers"])
    job           = concat(local.common_keys, ["image", "command", "args", "task_count", "parallelism", "max_retries", "timeout", "schedules"])
    "worker-pool" = concat(local.common_keys, ["image", "command", "args", "instances"])
    function      = concat(local.common_keys, ["public", "ingress", "min_instances", "max_instances", "concurrency", "timeout", "invokers", "triggers"])
  }

  product    = var.spec.product
  env_cfg    = var.platform.envs[var.env]
  project_id = try(var.spec.projects[var.env], "${var.platform.org}-${local.product}-${var.env}")
  region     = try(var.spec.region, var.platform.region)

  raw_components = try(var.spec.components, {})
  overrides      = try(var.spec.overrides[var.env], {})
  merged         = { for k, c in local.raw_components : k => merge(c, try(local.overrides[k], {})) }
  c = jsondecode(replace(replace(replace(jsonencode(local.merged),
    "{env}", var.env),
    "{project}", local.project_id),
  "{product}", local.product))

  type_of  = { for k, c in local.c : k => lookup(local.kinds, try(c.kind, ""), "invalid") }
  name_of  = { for k, t in local.type_of : k => "${local.product}-${k}-${lookup(local.codes, t, "x")}" }
  ref_of   = { for k, t in local.type_of : k => "${t}/${k}" }
  http     = [for k, t in local.type_of : k if contains(["service", "function"], t)]
  calls_of = { for k, c in local.c : k => try(tolist(c.calls), []) }

  # ---- validation (all problems reported together)
  errors = concat(
    [for k, t in local.type_of : "${k}: kind must be one of ${join(", ", keys(local.kinds))}" if t == "invalid"],
    flatten([for k, c in local.c : [
      for key in keys(c) : "${k}: unknown key '${key}' for kind ${try(c.kind, "?")}"
      if local.type_of[k] != "invalid" && !contains(local.allowed_keys[local.type_of[k]], key)
    ]]),
    flatten([for k, calls in local.calls_of : [
      for t in calls : "${k}: calls '${t}', which isn't a web/api/function component of this product"
      if !contains(local.http, t)
    ]]),
    [for k, c in local.c : "${k}: public is only allowed for web/api/function"
    if try(c.public, false) && !contains(["service", "function"], local.type_of[k])],
    [for k in keys(local.overrides) : "overrides.${var.env}.${k}: no such component" if !contains(keys(local.c), k)],
  )

  # ---- calls -> URLs + invoker grants
  any_calls      = length(flatten(values(local.calls_of))) > 0
  project_number = local.any_calls ? data.google_project.this[0].number : ""
  url_of         = { for k in local.http : k => "https://${local.name_of[k]}-${local.project_number}.${local.region}.run.app" }
  call_env = {
    for k, calls in local.calls_of : k => {
      for t in calls : "${upper(replace(t, "-", "_"))}_URL" => lookup(local.url_of, t, "")
    }
  }
  callers_of = { for t in local.http : t => [for k, calls in local.calls_of : local.ref_of[k] if contains(calls, t)] }

  invokers_of = {
    for k in local.http : k => distinct(concat(
      [for i in try(local.c[k].invokers, []) : contains(keys(local.c), i) ? local.ref_of[i] : i],
      local.callers_of[k],
      try(local.c[k].public, false) ? ["allUsers"] : [],
    ))
  }
  ingress_of = {
    for k in local.http : k => try(local.c[k].public, false) ? "INGRESS_TRAFFIC_ALL" : try(local.c[k].ingress, null)
  }

  # Fields shared by every type. null = use the product module's default.
  base = {
    for k, c in local.c : k => {
      env        = merge({ ENV = var.env, PRODUCT = local.product, COMPONENT = k }, local.call_env[k], try(c.env, {}))
      secret_env = try(c.secret_env, null)
      cpu        = try(tostring(c.cpu), null)
      memory     = try(c.memory, null)
      use_vpc    = try(c.use_vpc, null)
      access     = try(c.access, null)
    }
  }
  container = {
    for k, c in local.c : k => {
      image   = try(c.image, null)
      command = try(c.command, null)
      args    = try(c.args, null)
    }
  }
}

data "google_project" "this" {
  count      = local.any_calls ? 1 : 0
  project_id = local.project_id
}

resource "terraform_data" "validate" {
  input = local.product
  lifecycle {
    precondition {
      condition     = length(local.errors) == 0
      error_message = "product.yaml has problems:\n  - ${join("\n  - ", local.errors)}"
    }
  }
}

module "product" {
  source = "../product"

  product             = local.product
  team                = var.spec.team
  env                 = var.env
  project_id          = local.project_id
  region              = local.region
  labels              = try(var.spec.labels, {})
  vpc                 = try(local.env_cfg.vpc, null)
  deployers           = try(var.platform.deployers, [])
  deletion_protection = try(local.env_cfg.deletion_protection, true)

  services = {
    for k, c in local.c : k => merge(local.base[k], local.container[k], {
      port          = try(c.port, null)
      ingress       = local.ingress_of[k]
      min_instances = try(c.min_instances, null)
      max_instances = try(c.max_instances, null)
      concurrency   = try(c.concurrency, null)
      timeout       = try(c.timeout, null)
      cpu_idle      = try(c.cpu_idle, null)
      invokers      = local.invokers_of[k]
    }) if local.type_of[k] == "service"
  }

  jobs = {
    for k, c in local.c : k => merge(local.base[k], local.container[k], {
      task_count  = try(c.task_count, null)
      parallelism = try(c.parallelism, null)
      max_retries = try(c.max_retries, null)
      timeout     = try(c.timeout, null)
      schedules   = try(c.schedules, null)
    }) if local.type_of[k] == "job"
  }

  worker_pools = {
    for k, c in local.c : k => merge(local.base[k], local.container[k], {
      instances = try(c.instances, null)
    }) if local.type_of[k] == "worker-pool"
  }

  functions = {
    for k, c in local.c : k => merge(local.base[k], {
      ingress       = local.ingress_of[k]
      min_instances = try(c.min_instances, null)
      max_instances = try(c.max_instances, null)
      concurrency   = try(c.concurrency, null)
      timeout       = try(c.timeout, null)
      invokers      = local.invokers_of[k]
      triggers      = try(c.triggers, null)
    }) if local.type_of[k] == "function"
  }

  depends_on = [terraform_data.validate]
}

output "project_id" {
  value = local.project_id
}

output "region" {
  value = local.region
}

output "workloads" {
  value = module.product.workloads
}
