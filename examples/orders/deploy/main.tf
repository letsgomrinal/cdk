# Product "orders": one API, two jobs, one worker pool, one function.
#
# In a real unit the source is a pinned git ref, never a relative path:
#   source = "git::https://github.com/letsgomrinal/cdk.git//modules/product?ref=v0.1.0"
# This example lives inside the kit repo, so it uses a local path to test the current code.

module "orders" {
  source = "../../../modules/product"

  product             = "orders"
  team                = "commerce"
  env                 = var.env
  project_id          = var.project_id
  region              = var.region
  vpc                 = var.vpc
  deployers           = var.deployers
  deletion_protection = var.deletion_protection

  services = {
    # -> Cloud Run service "orders-api-svc", SA orders-api-svc@...
    api = {
      memory     = "1Gi"
      secret_env = { DB_URL = "orders-db-url" } # secretAccessor on this secret only
      ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
      invokers   = ["job/reconcile"] # reconcile job may call the API
      access = {
        publish = ["orders-events"]
      }
    }
  }

  jobs = {
    # -> orders-nightly-export-job
    nightly-export = {
      args       = ["export"]
      secret_env = { DB_URL = "orders-db-url" }
      access = {
        buckets           = { "acme-orders-exports-${var.env}" = "write" }
        bigquery_datasets = { "orders_analytics" = "write" }
      }
      schedules = {
        daily = { cron = "0 2 * * *", time_zone = "Europe/Berlin" }
      }
    }

    # -> orders-reconcile-job
    reconcile = {
      args       = ["reconcile"]
      task_count = 4
      schedules = {
        hourly = { cron = "15 * * * *" }
        weekly = { cron = "0 4 * * 0", args = ["reconcile", "--full"] }
      }
    }
  }

  worker_pools = {
    # -> orders-email-sender-wp
    email-sender = {
      args       = ["worker", "email"]
      instances  = 2
      secret_env = { SMTP_PASSWORD = "orders-smtp-password:3" } # version pinned
      access = {
        subscribe = ["orders-email-requests-sub"]
        buckets   = { "acme-orders-templates" = "read" }
      }
    }
  }

  functions = {
    # -> orders-gcs-ingest-fn
    gcs-ingest = {
      memory = "1Gi"
      access = {
        buckets = { "acme-orders-inbox-${var.env}" = "read" }
        publish = ["orders-events"]
      }
      triggers = {
        upload = {
          event_type = "google.cloud.storage.object.v1.finalized"
          filters    = { bucket = "acme-orders-inbox-${var.env}" }
        }
      }
    }
  }
}

output "workloads" {
  value = module.orders.workloads
}
