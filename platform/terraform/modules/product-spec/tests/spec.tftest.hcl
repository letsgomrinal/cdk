# Offline tests for the product.yaml -> Cloud Run translation (mocked provider).
#   cd modules/product-spec && terraform init -backend=false && terraform test

mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789" }
  }
  mock_resource "google_service_account" {
    defaults = { name = "projects/p/serviceAccounts/mock@p.iam.gserviceaccount.com" }
  }
  mock_resource "google_cloud_run_v2_job" {
    defaults = { id = "projects/p/locations/europe-west1/jobs/mock" }
  }
}

variables {
  env = "prod"
  platform = {
    org       = "acme"
    region    = "europe-west1"
    deployers = ["serviceAccount:drone-release@acme-cicd.iam.gserviceaccount.com"]
    envs = {
      dev  = { state_bucket = "acme-tfstate-dev", deletion_protection = false }
      prod = { state_bucket = "acme-tfstate-prod" }
    }
  }
  spec = {
    product = "orders"
    team    = "commerce"
    envs    = ["dev", "prod"]
    apps = {
      storefront = { template = "nextjs", public = true, calls = ["backend"] }
    }
    apis = {
      backend = { secret_env = { DB_URL = "orders-db-url" }, invokers = ["reconcile"] }
    }
    jobs = {
      reconcile = { schedules = { hourly = { cron = "15 * * * *" } } }
    }
    workers = {
      email = { instances = 1, access = { buckets = { "acme-orders-{env}" = "read" } } }
    }
    functions = {
      ingest = { triggers = { up = { event_type = "google.cloud.storage.object.v1.finalized", filters = { bucket = "b" } } } }
    }
    overrides = {
      prod = { workers = { email = { instances = 4 } } }
    }
  }
}

run "translates_sections_and_wiring" {
  command = plan

  assert {
    condition     = output.project_id == "acme-orders-prod"
    error_message = "Project should default to {org}-{product}-{env}."
  }
  assert {
    condition     = output.workloads["service/storefront"].name == "orders-storefront-svc" && output.workloads["service/backend"].name == "orders-backend-svc" && output.workloads["worker-pool/email"].type == "worker-pool"
    error_message = "apps and apis should both become Cloud Run services."
  }
  assert {
    condition     = local.call_env["storefront"]["BACKEND_URL"] == "https://orders-backend-svc-123456789.europe-west1.run.app"
    error_message = "calls should inject <TARGET>_URL."
  }
  assert {
    condition     = local.base["reconcile"].env["ENV"] == "prod" && local.base["reconcile"].env["COMPONENT"] == "reconcile"
    error_message = "Standard env vars should be injected."
  }
  assert {
    condition     = toset(local.invokers_of["backend"]) == toset(["job/reconcile", "service/storefront"])
    error_message = "Invokers: bare component names resolve to refs, and callers are added."
  }
  assert {
    condition     = toset(local.invokers_of["storefront"]) == toset(["allUsers"]) && local.ingress_of["storefront"] == "INGRESS_TRAFFIC_ALL"
    error_message = "public: true should open ingress and allow allUsers."
  }
  assert {
    condition     = local.c["email"].instances == 4
    error_message = "prod override should apply."
  }
  assert {
    condition     = contains(keys(local.c["email"].access.buckets), "acme-orders-prod")
    error_message = "{env} placeholder should be substituted."
  }
  assert {
    condition     = length(local.errors) == 0
    error_message = "Valid spec should produce no errors."
  }
}

run "dev_has_no_override" {
  command = plan
  variables {
    env = "dev"
  }
  assert {
    condition     = local.c["email"].instances == 1 && output.project_id == "acme-orders-dev"
    error_message = "Overrides are per env."
  }
}

run "rejects_bad_spec" {
  command = plan
  variables {
    spec = {
      product = "orders"
      team    = "commerce"
      apis = {
        api  = { min_instance = 2 } # typo
        dupe = {}
      }
      jobs = {
        job1 = { public = true } # public job
        dupe = {}                # same name in two sections
      }
      apps = {
        caller = { calls = ["nope"] } # unknown target
      }
      overrides = { prod = { apis = { ghost = { memory = "1Gi" } } } }
    }
  }
  expect_failures = [terraform_data.validate]
}

run "empty_sections_are_fine" {
  command = plan
  variables {
    spec = {
      product = "orders"
      team    = "commerce"
      apps    = null
      jobs    = { nightly = null }
    }
  }
  assert {
    condition     = output.workloads["job/nightly"].name == "orders-nightly-job" && length(output.workloads) == 1
    error_message = "A null section or a component with no settings should work."
  }
}
