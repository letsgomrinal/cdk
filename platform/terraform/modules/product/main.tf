# A product is the deployable unit: any mix of services, jobs, worker pools and
# functions, with any number of each. A product that only needs two jobs sets
# `jobs` and leaves the other maps empty.
#
# What happens for each workload:
#   1. naming      -> {product}-{workload}-{svc|job|wp|fn}
#   2. identity    -> a dedicated SA with the same ID, plus resource-level grants
#   3. resource    -> the Cloud Run service / job / worker pool / function
#   4. access      -> invoker grants between workloads, release grants for deployers

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = ">= 8.0" }
  }
}

locals {
  workloads = merge(
    { for k, v in var.services : "service/${k}" => { type = "service", name = k, spec = v } },
    { for k, v in var.jobs : "job/${k}" => { type = "job", name = k, spec = v } },
    { for k, v in var.worker_pools : "worker-pool/${k}" => { type = "worker-pool", name = k, spec = v } },
    { for k, v in var.functions : "function/${k}" => { type = "function", name = k, spec = v } },
  )

  # Secrets used in secret_env are granted automatically, so nobody has to list them twice.
  secrets_from_env = {
    for key, w in local.workloads : key => [for ref in values(w.spec.secret_env) : split(":", ref)[0]]
  }

  vpc_for = {
    for key, w in local.workloads : key => (w.spec.use_vpc ? var.vpc : null)
  }
}

# ---------------------------------------------------------------- naming

module "naming" {
  source   = "../naming"
  for_each = local.workloads

  product      = var.product
  workload     = each.value.name
  type         = each.value.type
  env          = var.env
  team         = var.team
  project_id   = var.project_id
  extra_labels = var.labels
}

# ---------------------------------------------------------------- identity

module "identity" {
  source   = "../workload-identity"
  for_each = local.workloads

  project_id   = var.project_id
  account_id   = module.naming[each.key].service_account_id
  display_name = module.naming[each.key].service_account_display_name
  description  = "Runtime identity for ${each.key} in product ${var.product}. Managed by terraform (cdk)."
  deployers    = var.deployers

  access = merge(each.value.spec.access, {
    secrets = distinct(concat(each.value.spec.access.secrets, local.secrets_from_env[each.key]))
  })
}

# ---------------------------------------------------------------- workloads

module "service" {
  source   = "../cloud-run-service"
  for_each = var.services

  project_id            = var.project_id
  region                = var.region
  name                  = module.naming["service/${each.key}"].name
  labels                = module.naming["service/${each.key}"].labels
  service_account_email = module.identity["service/${each.key}"].email
  vpc                   = local.vpc_for["service/${each.key}"]
  deletion_protection   = var.deletion_protection

  image         = coalesce(each.value.image, "us-docker.pkg.dev/cloudrun/container/hello")
  command       = each.value.command
  args          = each.value.args
  env           = each.value.env
  secret_env    = each.value.secret_env
  cpu           = each.value.cpu
  memory        = each.value.memory
  port          = each.value.port
  ingress       = each.value.ingress
  min_instances = each.value.min_instances
  max_instances = each.value.max_instances
  concurrency   = each.value.concurrency
  timeout       = each.value.timeout
  cpu_idle      = each.value.cpu_idle
}

module "job" {
  source   = "../cloud-run-job"
  for_each = var.jobs

  project_id            = var.project_id
  region                = var.region
  name                  = module.naming["job/${each.key}"].name
  labels                = module.naming["job/${each.key}"].labels
  service_account_email = module.identity["job/${each.key}"].email
  vpc                   = local.vpc_for["job/${each.key}"]
  deletion_protection   = var.deletion_protection

  image       = coalesce(each.value.image, "us-docker.pkg.dev/cloudrun/container/job")
  command     = each.value.command
  args        = each.value.args
  env         = each.value.env
  secret_env  = each.value.secret_env
  cpu         = each.value.cpu
  memory      = each.value.memory
  task_count  = each.value.task_count
  parallelism = each.value.parallelism
  max_retries = each.value.max_retries
  timeout     = each.value.timeout
  schedules   = each.value.schedules
}

module "worker_pool" {
  source   = "../cloud-run-worker-pool"
  for_each = var.worker_pools

  project_id            = var.project_id
  region                = var.region
  name                  = module.naming["worker-pool/${each.key}"].name
  labels                = module.naming["worker-pool/${each.key}"].labels
  service_account_email = module.identity["worker-pool/${each.key}"].email
  vpc                   = local.vpc_for["worker-pool/${each.key}"]
  deletion_protection   = var.deletion_protection

  image      = coalesce(each.value.image, "us-docker.pkg.dev/cloudrun/container/hello")
  command    = each.value.command
  args       = each.value.args
  env        = each.value.env
  secret_env = each.value.secret_env
  cpu        = each.value.cpu
  memory     = each.value.memory
  instances  = each.value.instances
}

module "function" {
  source   = "../cloud-function"
  for_each = var.functions

  project_id            = var.project_id
  region                = var.region
  name                  = module.naming["function/${each.key}"].name
  labels                = module.naming["function/${each.key}"].labels
  service_account_email = module.identity["function/${each.key}"].email
  vpc                   = local.vpc_for["function/${each.key}"]
  deletion_protection   = var.deletion_protection

  env           = each.value.env
  secret_env    = each.value.secret_env
  cpu           = each.value.cpu
  memory        = each.value.memory
  ingress       = each.value.ingress
  min_instances = each.value.min_instances
  max_instances = each.value.max_instances
  concurrency   = each.value.concurrency
  timeout       = each.value.timeout
  triggers      = each.value.triggers
}

# ---------------------------------------------------------------- invokers
# The workload being called owns the grant: its own config lists who may call it.
# "job/reconcile" refers to a workload in this product; anything else is an IAM member.

locals {
  http_targets = merge(
    { for k, v in var.services : "service/${k}" => { name = module.service[k].name, invokers = v.invokers } },
    { for k, v in var.functions : "function/${k}" => { name = module.function[k].name, invokers = v.invokers } },
  )

  invoker_grants = merge([
    for target, t in local.http_targets : {
      for inv in t.invokers : "${target}|${inv}" => {
        service = t.name
        ref     = inv
        member  = can(regex("^(service|job|worker-pool|function)/", inv)) ? try(module.identity[inv].member, null) : inv
      }
    }
  ]...)
}

resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = local.invoker_grants
  project  = var.project_id
  location = var.region
  name     = each.value.service
  role     = "roles/run.invoker"
  member   = each.value.member

  lifecycle {
    precondition {
      condition     = each.value.member != null
      error_message = "Invoker '${each.value.ref}' isn't a workload in product '${var.product}'. Use <type>/<name> or an IAM member (serviceAccount:..., group:...)."
    }
  }
}

# ---------------------------------------------------------------- release grants
# Deployers (the Drone release identity) get roles/run.developer on each resource,
# and serviceAccountUser on each runtime SA (granted in workload-identity).

locals {
  deployer_on = {
    service       = { for k, m in module.service : k => m.name }
    job           = { for k, m in module.job : k => m.name }
    "worker-pool" = { for k, m in module.worker_pool : k => m.name }
    function      = { for k, m in module.function : k => m.name }
  }

  deployer_grants = {
    for type, resources in local.deployer_on : type => merge([
      for k, name in resources : { for d in var.deployers : "${type}/${k}|${d}" => { name = name, member = d } }
    ]...)
  }
}

resource "google_cloud_run_v2_service_iam_member" "deployers" {
  for_each = merge(local.deployer_grants["service"], local.deployer_grants["function"])
  project  = var.project_id
  location = var.region
  name     = each.value.name
  role     = "roles/run.developer"
  member   = each.value.member
}

resource "google_cloud_run_v2_job_iam_member" "deployers" {
  for_each = local.deployer_grants["job"]
  project  = var.project_id
  location = var.region
  name     = each.value.name
  role     = "roles/run.developer"
  member   = each.value.member
}

resource "google_cloud_run_v2_worker_pool_iam_member" "deployers" {
  for_each = local.deployer_grants["worker-pool"]
  project  = var.project_id
  location = var.region
  name     = each.value.name
  role     = "roles/run.developer"
  member   = each.value.member
}
