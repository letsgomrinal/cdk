# Conventions

These are enforced in code (variable validations, `terraform test`, copier
validators) wherever possible. Where something can't be enforced, it's a
code-review rule.

## 1. Vocabulary

| Term | Meaning | Example |
|---|---|---|
| **product** | The deployable unit: one folder, one Terraform root, one Drone pipeline | `orders` |
| **workload** | One runnable thing inside a product | `nightly-export` |
| **type** | `service`, `job`, `worker-pool`, `function` | `job` |
| **env** | `dev`, `staging`, `prod`. **One GCP project per product per env** | `acme-orders-prod` |

A product can contain any mix of types, and any number of workloads of each type.

## 2. Names

```
{product}-{workload}-{type_code}        type_code: svc | job | wp | fn
```

The same string is used for:

| Thing | Name |
|---|---|
| Cloud Run service / job / worker pool / function | `orders-nightly-export-job` |
| Runtime service account ID | `orders-nightly-export-job@acme-orders-dev.iam.gserviceaccount.com` |
| Scheduler jobs | `orders-nightly-export-job-{schedule}` e.g. `…-job-daily` |
| Eventarc triggers | `orders-gcs-ingest-fn-{trigger}` e.g. `…-fn-upload` |
| Atlantis project | `{product}-{env}` e.g. `orders-prod` |
| Terraform state | `gs://{org}-tfstate-{env}/products/{product}/default.tfstate` |
| Image | `{region}-docker.pkg.dev/{org}-artifacts/products/{product}:{sha12}` |

Rules:

* **product**: `^[a-z][a-z0-9]{1,9}$`, 2–10 chars, **no hyphens**. Since it never
  contains a hyphen, the first `-` in a name always ends the product, so names
  parse cleanly (`${PROJECT_NAME%%-*}`, `release.sh`).
* **workload**: `^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$`, 1–15 chars.
* 10 + 1 + 15 + 1 + 3 = **30**, exactly the service account ID limit. Any name
  that passes validation therefore fits, so the kit never truncates or hashes a name.
  Audit logs show `orders-nightly-export-job@…` and you know exactly what it is.
* **env is not in resource names.** Environments are separated by project. If
  two envs ever share a project, the names collide. That's intended: it stops
  someone quietly putting dev and prod in one project.
* The type suffix lets a service and a function share a workload name
  (`orders-ingest-svc` vs `orders-ingest-fn`) without colliding.

## 3. Labels

Applied to every resource and revision:

| Label | Value |
|---|---|
| `product` | `orders` |
| `workload` | `nightly-export` |
| `workload-type` | `service` / `job` / `worker-pool` / `function` |
| `env` | `dev` |
| `team` | `commerce` |
| `managed-by` | `terraform` |

The release script uses `product` + `workload-type` to find what to deploy.
Billing exports can group cost by `product`, `team` and `workload`.

## 4. Identity & IAM

**One service account per workload. Never shared, never the default compute SA.**

Each workload declares what it needs, and the kit grants it on that single resource:

```hcl
jobs = {
  nightly-export = {
    secret_env = { DB_URL = "orders-db-url" }        # accessor on this secret is granted automatically
    access = {
      secrets           = ["orders-api-key"]         # roles/secretmanager.secretAccessor  (secret)
      buckets           = { "orders-exports" = "write" }
      publish           = ["orders-events"]          # roles/pubsub.publisher              (topic)
      subscribe         = ["orders-email-sub"]       # roles/pubsub.subscriber             (subscription)
      bigquery_datasets = { "orders_analytics" = "write" }
      project_roles     = []                         # escape hatch, needs a reason in review
    }
  }
}
```

| `access` key | Mode | Role | Scope |
|---|---|---|---|
| `secrets` | n/a | `secretmanager.secretAccessor` | the secret |
| `buckets` | `read` | `storage.objectViewer` | the bucket |
| | `write` | `storage.objectUser` (CRUD objects, no IAM/bucket admin) | the bucket |
| | `admin` | `storage.objectAdmin` | the bucket |
| `publish` | n/a | `pubsub.publisher` | the topic |
| `subscribe` | n/a | `pubsub.subscriber` | the subscription |
| `bigquery_datasets` | `read` / `write` | `bigquery.dataViewer` / `dataEditor` | the dataset (`project:dataset` for cross-project) |
| `project_roles` | n/a | as listed | project (basic roles and impersonation roles are rejected) |

Cross-project resources take full IDs: `projects/shared/secrets/x`, `projects/p/topics/t`.

### Grants the kit adds by itself

| Grant | To | On | Why |
|---|---|---|---|
| `run.invoker` | entries in `invokers` | that service/function | caller allowlist |
| `run.invoker` | the job's own SA | that job | Cloud Scheduler runs the job as the job's SA |
| `run.invoker` | the function's own SA | that function | Eventarc delivers as the function's SA |
| `eventarc.eventReceiver` | the function's own SA | project (no narrower scope exists) | only if it has triggers |
| `run.developer` | `deployers` | each resource | Drone can roll out new revisions |
| `iam.serviceAccountUser` | `deployers` | each runtime SA (**not** the project) | Drone can deploy revisions that run as that SA |

### Calling one workload from another

**The called workload owns the grant.** A service lists who may call it:

```hcl
services = {
  api = { invokers = ["job/reconcile", "serviceAccount:x@other.iam.gserviceaccount.com"] }
}
```

`<type>/<name>` refers to a workload in the same product. A typo fails the plan.

### All IAM is additive

The kit only uses `*_iam_member`, never `*_iam_binding` / `*_iam_policy`, so it
can't remove grants managed by other stacks.

## 5. Who owns what

| | Owner | Tool | Changes via |
|---|---|---|---|
| Projects, VPC, state buckets, Artifact Registry, Drone release SA, secret containers | Platform | foundation stack (not this kit) | Atlantis |
| Workload config: scaling, env, IAM, schedules, triggers | Product team | `modules/product` | PR → Atlantis plan/apply |
| Code / image | Product team | Drone + `deploy/release.sh` | merge to main → dev, `drone promote` → prod |

The Cloud Run modules have `ignore_changes` on the container image, so Atlantis
applies never roll back a release, and releases never need an Atlantis run.

### What the foundation must provide

* One project per product per env: `{org}-{product}-{env}`
* State bucket per env: `{org}-tfstate-{env}`, writable by the Atlantis SA
* Artifact Registry `{org}-artifacts/products`, which runtime SAs can read
  (Cloud Run pulls images with the service agent, so grant
  `artifactregistry.reader` to each env project's Cloud Run service agent)
* Drone release SA `drone-release@{org}-cicd`, with Cloud Build + source bucket
  permissions in each project if you deploy functions from source
* For GCS-triggered functions: `pubsub.publisher` for the project's GCS service agent
* Secret *containers* (values are set out-of-band; Terraform never sees secret values)

## 6. Unit layout and portability

```
<product>/
├── unit.yaml              # product, team, kit_version, envs
├── atlantis.yaml          # standalone repos only (generated)
├── .drone.yml             # standalone repos only
├── Dockerfile  src/  functions/<name>/
└── deploy/
    ├── versions.tf        # backend prefix = products/<product>
    ├── main.tf            # module "product" { source = "git::…?ref=vX.Y.Z" }
    ├── variables.tf
    ├── release.sh
    └── env/<env>.tfvars  env/<env>.backend.hcl
```

What makes the folder portable (it moves between a micro repo and a monorepo unchanged):

1. **No `../` outside the unit.** The kit is pinned by git ref.
2. **State is keyed by product, not repo path.**
3. **Atlantis config is generated** from `unit.yaml` (`tools/gen-atlantis.py`),
   because Atlantis reads one `atlantis.yaml` per repo.
4. **Release discovers workloads by label**, so no repo-specific lists.
