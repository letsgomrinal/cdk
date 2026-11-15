# Offline tests with a mocked provider. No GCP credentials needed.
#   cd modules/product && terraform init && terraform test

mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789" }
  }
  mock_resource "google_service_account" {
    defaults = {
      name = "projects/p/serviceAccounts/mock@p.iam.gserviceaccount.com"
    }
  }
  mock_resource "google_cloud_run_v2_job" {
    defaults = {
      id = "projects/p/locations/europe-west1/jobs/mock"
    }
  }
}

variables {
  product    = "orders"
  env        = "dev"
  team       = "commerce"
  project_id = "acme-orders-dev"
  region     = "europe-west1"
  deployers  = ["serviceAccount:drone-release@acme-cicd.iam.gserviceaccount.com"]
}

run "naming_and_identity" {
  command = plan

  variables {
    services = {
      api = { secret_env = { DB_URL = "orders-db-url" }, invokers = ["job/reconcile"] }
    }
    jobs = {
      reconcile = { schedules = { hourly = { cron = "0 * * * *" } } }
    }
    worker_pools = {
      email-sender = { access = { subscribe = ["email-sub"] } }
    }
  }

  assert {
    condition     = module.naming["service/api"].name == "orders-api-svc"
    error_message = "Service name should be {product}-{workload}-svc."
  }

  assert {
    condition     = module.naming["worker-pool/email-sender"].service_account_id == "orders-email-sender-wp"
    error_message = "Worker pool SA id should be {product}-{workload}-wp."
  }

  assert {
    condition     = module.naming["job/reconcile"].labels["workload-type"] == "job"
    error_message = "Standard labels missing."
  }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.invokers) == 1
    error_message = "job/reconcile should be granted run.invoker on the api."
  }

  assert {
    condition     = length(google_cloud_run_v2_job_iam_member.deployers) == 1 && length(google_cloud_run_v2_worker_pool_iam_member.deployers) == 1
    error_message = "Deployers should get run.developer on each resource."
  }
}

run "calls_egress_and_runtime_options" {
  command = plan

  variables {
    vpc = { network = "net", subnetwork = "sub" }
    services = {
      backend = {
        labels            = { tier = "critical" }
        egress            = "ALL_TRAFFIC"
        startup_cpu_boost = true
        startup_probe     = { http_path = "/healthz" }
        liveness_probe    = { period_seconds = 30 }
      }
      web = { calls = ["service/backend"], egress = "NONE" }
    }
    jobs = {
      sync = { calls = ["service/backend"], execution_environment = "EXECUTION_ENVIRONMENT_GEN2" }
    }
    worker_pools = {
      mailer = { startup_probe = { http_path = "/ready", port = 9000 } }
    }
  }

  assert {
    condition     = local.env_for["service/web"]["BACKEND_URL"] == "https://orders-backend-svc-123456789.europe-west1.run.app"
    error_message = "calls should inject <TARGET>_URL."
  }
  assert {
    condition     = toset(local.invokers_of["service/backend"]) == toset(["service/web", "job/sync"])
    error_message = "Callers should be granted run.invoker on the target."
  }
  assert {
    condition     = local.vpc_for["service/web"] == null && local.vpc_for["service/backend"].egress == "ALL_TRAFFIC"
    error_message = "Egress is per workload; NONE means no VPC."
  }
  assert {
    condition     = module.naming["service/backend"].labels["tier"] == "critical" && !contains(keys(module.naming["service/web"].labels), "tier")
    error_message = "Workload labels apply to that workload only."
  }
  assert {
    condition     = local.vpc_for["worker-pool/mailer"].egress == "PRIVATE_RANGES_ONLY"
    error_message = "Default egress is private ranges."
  }
}

run "rejects_calls_to_non_http_targets" {
  command = plan
  variables {
    jobs = { a = {}, b = { calls = ["job/a"] } }
  }
  expect_failures = [terraform_data.calls]
}

run "rejects_long_product" {
  command = plan
  variables {
    product = "ordersplatform"
  }
  expect_failures = [var.product]
}

run "rejects_long_workload_name" {
  command = plan
  variables {
    jobs = { "this-name-is-way-too-long" = {} }
  }
  expect_failures = [var.jobs]
}

run "rejects_unknown_invoker_ref" {
  command = plan
  variables {
    services = { api = { invokers = ["job/does-not-exist"] } }
  }
  expect_failures = [google_cloud_run_v2_service_iam_member.invokers]
}
