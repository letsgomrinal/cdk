# Turns a product.yaml (plus the repo-wide platform.yaml) into a call to
# modules/product. The section a component sits in decides its Cloud Run type:
#
#   section    -> type          notes
#   apps       -> service       frontends (Next.js, React); `public: true` opens it to the internet
#   apis       -> service       backends (FastAPI, ...); internal by default
#   jobs       -> job           run-to-completion, optional schedules
#   workers    -> worker-pool   always-on consumers
#   functions  -> function      Eventarc-triggered
#
# Component names are unique across the whole product (they name the code folder
# products/<product>/<section>/<name>/ and the Cloud Run resource).
#
# product.yaml extras handled here:
#   calls: [backend]          -> caller gets run.invoker on backend, plus env BACKEND_URL
#   public: true              -> ingress ALL + allUsers invoker (apps/apis/functions only)
#   overrides.<env>.<section> -> per-env, per-component shallow merge (e.g. prod sizing)
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
  sections = {
    apps      = "service"
    apis      = "service"
    jobs      = "job"
    workers   = "worker-pool"
    functions = "function"
  }
  codes = { service = "svc", job = "job", "worker-pool" = "wp", function = "fn" }

  common_keys = ["template", "env", "secret_env", "cpu", "memory", "use_vpc", "access", "calls"]
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

  # A section written as `jobs:` with nothing under it decodes to null.
  # try() instead of `x == null ? {} : x`, because the two branches have different types.
  sec       = { for s in keys(local.sections) : s => try({ for n, c in var.spec[s] : n => c }, {}) }
  overrides = try({ for s, v in var.spec.overrides[var.env] : s => v }, {})
  all_names = flatten([for s, comps in local.sec : keys(comps)])

  merged = merge([for s, comps in local.sec : {
    for n, c in comps : n => merge(try({ for k, v in c : k => v }, {}), try(local.overrides[s][n], {}))
  }]...)
  c = jsondecode(replace(replace(replace(jsonencode(local.merged),
    "{env}", var.env),
    "{project}", local.project_id),
  "{product}", local.product))

  section_of = merge([for s, comps in local.sec : { for n in keys(comps) : n => s }]...)
  type_of    = { for n, s in local.section_of : n => local.sections[s] }
  name_of    = { for k, t in local.type_of : k => "${local.product}-${k}-${local.codes[t]}" }
  ref_of     = { for k, t in local.type_of : k => "${t}/${k}" }
  http       = [for k, t in local.type_of : k if contains(["service", "function"], t)]
  calls_of   = { for k, c in local.c : k => try(tolist(c.calls), []) }

  # ---- validation (all problems reported together)
  errors = concat(
    [for n in distinct(local.all_names) : "component '${n}' is defined in more than one section; names must be unique in a product"
    if length([for x in local.all_names : x if x == n]) > 1],
    flatten([for k, c in local.c : [
      for key in keys(c) : "${local.section_of[k]}.${k}: unknown key '${key}'"
      if !contains(local.allowed_keys[local.type_of[k]], key)
    ]]),
    flatten([for k, calls in local.calls_of : [
      for t in calls : "${local.section_of[k]}.${k}: calls '${t}', which isn't an app, api or function of this product"
      if !contains(local.http, t)
    ]]),
    [for k, c in local.c : "${local.section_of[k]}.${k}: public is only allowed for apps, apis and functions"
    if try(c.public, false) && !contains(["service", "function"], local.type_of[k])],
    flatten([for s, comps in local.overrides : concat(
      contains(keys(local.sections), s) ? [] : ["overrides.${var.env}.${s}: not a section (${join(", ", keys(local.sections))})"],
      [for n in keys(comps) : "overrides.${var.env}.${s}.${n}: no such component in ${s}"
      if contains(keys(local.sections), s) && !contains(keys(local.sec[s]), n)],
    )]),
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
