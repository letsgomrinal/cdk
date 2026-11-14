# cdk: serverless deployment kit for GCP

Terraform modules and a unit template for deploying **Cloud Run services, jobs,
worker pools and Cloud Run functions**, with consistent naming, one service
account per workload, and resource-level IAM. Infra goes through **Atlantis**;
releases go through **Drone**.

```hcl
module "orders" {
  source = "git::https://github.com/letsgomrinal/cdk.git//modules/product?ref=v0.1.0"

  product    = "orders"
  team       = "commerce"
  env        = var.env
  project_id = var.project_id
  region     = var.region
  deployers  = ["serviceAccount:drone-release@acme-cicd.iam.gserviceaccount.com"]

  services     = { api = { secret_env = { DB_URL = "orders-db-url" }, invokers = ["job/reconcile"] } }
  jobs         = { reconcile = { schedules = { hourly = { cron = "15 * * * *" } } } }
  worker_pools = { email-sender = { access = { subscribe = ["orders-email-sub"] } } }
  functions    = {}   # use only the types you need
}
```

This creates `orders-api-svc`, `orders-reconcile-job` and `orders-email-sender-wp`.
Each runs as a service account with the same name, which can access only
the secret, subscription or service it was given.

## Layout

```
modules/
  product/                # entry point: maps of services / jobs / worker_pools / functions
  naming/                 # the naming convention (pure, no resources)
  workload-identity/      # SA per workload + resource-level IAM grants
  cloud-run-service/
  cloud-run-job/          # + Cloud Scheduler
  cloud-run-worker-pool/
  cloud-function/         # Cloud Run service + Eventarc triggers
templates/product/        # copier template for a new product unit
examples/orders/          # a complete unit: 1 service, 2 jobs, 1 worker pool, 1 function
atlantis/repos.yaml       # server-side Atlantis workflow "cdk"
tools/gen-atlantis.py     # builds atlantis.yaml from unit.yaml files
docs/CONVENTIONS.md       # naming, labels, IAM, ownership: read this
```

## Creating a product

```bash
pipx install copier
```

```bash
copier copy --vcs-ref v0.1.0 https://github.com/letsgomrinal/cdk.git services/billing
```

```bash
tools/gen-atlantis.py . > atlantis.yaml
```

Copier prompts for product code, team, envs and region, and validates the
product code. Later template changes come in with `copier update --vcs-ref v0.2.0`.

## Micro repo or monorepo

A unit is self-contained, so the same folder works in either setup:

```
billing/  (micro repo)                 platform/  (monorepo)
├── unit.yaml                          ├── atlantis.yaml   ← generated from all unit.yaml
├── atlantis.yaml   ← generated        ├── .drone.star     ← one pipeline per changed unit
├── .drone.yml                         ├── services/billing/   (same folder as left)
└── deploy/ …                          ├── services/orders/
                                       └── jobs/reporting/
```

* **Atlantis:** Atlantis reads only the repo-root `atlantis.yaml`, so generate
  it with `tools/gen-atlantis.py`. In CI, `--check` fails the build if it's stale.
  Project names are `{product}-{env}`, so they're unique across a monorepo.
* **Drone:** in a micro repo the unit's `.drone.yml` is used as-is. In a monorepo,
  Drone has no built-in path filtering. Use a `.drone.star` that emits one pipeline
  per unit (the unit's steps, run with that unit as the working directory), plus the
  [paths-changed converter](https://github.com/meltwater/drone-convert-pathschanged)
  so only changed units build.
* **Kit versions:** each unit pins its own `?ref=`, so units in a monorepo
  upgrade independently.

## Infra vs releases

```
PR touching deploy/  ──► Atlantis plan (per env) ──► approve ──► atlantis apply
merge to main        ──► Drone: build image once ──► release.sh → dev
drone promote prod   ──► Drone: same image        ──► release.sh → prod
```

Terraform ignores the container image, so the two paths never conflict. See
[docs/CONVENTIONS.md §5](docs/CONVENTIONS.md#5-who-owns-what).

## Atlantis setup

Load `atlantis/repos.yaml` as the server-side repo config. For each project it:

* uses `TF_DATA_DIR=.terraform-<env>`, so parallel dev/prod plans in the same dir don't collide
* inits with `env/<env>.backend.hcl` (a separate state bucket per env)
* plans with `env/<env>.tfvars`

## Developing the kit

```bash
terraform fmt -recursive
```

```bash
cd modules/product && terraform init -backend=false && terraform test
```

Tests use a mocked provider, so they need no GCP credentials. They check names,
generated grants, and that invalid input (long names, unknown invoker refs,
basic roles) is rejected. Requires Terraform ≥ 1.7 for tests (modules need ≥ 1.6)
and google provider ≥ 8.0 (worker pools); developed against 8.11.

Release: tag `vX.Y.Z`. Units bump `?ref=` and `kit_version` in `unit.yaml`.
