# Conventions

These are enforced in code (variable validations, `terraform test`, copier
validators) wherever possible. Where something can't be enforced, it's a
code-review rule.

## 1. Vocabulary

| Term | Meaning | Example |
|---|---|---|
| **product** | One folder `products/<product>/` with a `product.yaml`, and one Terraform state per env | `orders` |
| **component** | One deployable piece of a product: a code folder + one Cloud Run resource (a.k.a. workload) | `nightly-export` |
| **section** | The deployment type, as a folder: `apps`, `apis`, `jobs`, `workers`, `functions` | `jobs` |
| **type** | The Cloud Run resource: `service`, `job`, `worker-pool`, `function` | `job` |
| **env** | `dev`, `staging`, `prod`. **One GCP project per product per env** | `acme-orders-prod` |

A product can contain any mix of sections, and any number of components in each.
`apps` and `apis` both become Cloud Run services; they differ in template and defaults.
A component's path is always `products/<product>/<section>/<name>/`, and its runtime
config is the `deployment.yml` in that folder ([reference](DEPLOYMENT_YML.md)).

## 2. Names

```
{product}-{component}-{type_code}        type_code: svc | job | wp | fn
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
| Image | `{registry}/{product}/{component}:{sha12}` |

Rules:

* **product**: `^[a-z][a-z0-9]{1,9}$`, 2–10 chars, **no hyphens**. Since it never
  contains a hyphen, the first `-` in a name always ends the product, so names
  parse cleanly.
* **component**: `^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$`, 1–15 chars.
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

Billing exports can group cost by `product`, `team` and `workload`.

## 4. Identity & IAM

**One service account per workload. Never shared, never the default compute SA.**

Each component declares what it needs under `permissions:` in its `deployment.yml`, and the
kit grants it on that single resource:

```yaml
# products/orders/jobs/nightly-export/deployment.yml
env:
  DB_URL: { secret: orders-db-url }            # accessor on this secret is granted automatically
permissions:
  secrets: [orders-api-key]                    # roles/secretmanager.secretAccessor  (secret)
  buckets: { "acme-orders-exports-{env}": write }
  publish: [orders-events]                     # roles/pubsub.publisher              (topic)
  subscribe: [orders-email-sub]                # roles/pubsub.subscriber             (subscription)
  bigquery_datasets: { orders_analytics: write }
  project_roles: []                            # escape hatch, needs a reason in review
```

| `permissions` key | Mode | Role | Scope |
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

Inside a product, the caller declares it: `calls: [backend]` gives the caller's SA
`run.invoker` on `backend` and injects `BACKEND_URL`. A caller from outside the
product goes in the target's `permissions.invokers: ["serviceAccount:…"]`.
Unknown names fail `cdk sync`.

### All IAM is additive

The kit only uses `*_iam_member`, never `*_iam_binding` / `*_iam_policy`, so it
can't remove grants managed by other stacks.

## 5. Who owns what

| | Owner | Where | Changes via |
|---|---|---|---|
| Projects, VPC, state buckets, Artifact Registry, Drone release SA, secret containers | Platform | foundation stack (not this kit), described in `platform.yaml` | Atlantis |
| Components and their config: scaling, env, IAM, schedules, triggers | Product team | `products/<p>/<section>/<name>/deployment.yml` | PR → Atlantis plan/apply |
| Code | Product team | `products/<p>/<section>/<name>/` | merge → `cdk release dev`; `drone promote` → `cdk promote dev prod` |
| CI/CD, Atlantis workflow, modules, templates, `cdk` | Platform | `platform/`, `tools/`, repo root | PR (CODEOWNERS routes review) |

The Cloud Run modules have `ignore_changes` on the container image, so Atlantis
applies never roll back a release, and releases never need an Atlantis run.

### What the foundation must provide

* One project per product per env: `{org}-{product}-{env}` (or listed under `projects:` in product.yaml)
* State bucket per env (`platform.yaml: envs.<env>.state_bucket`), writable by the Atlantis SA
* Artifact Registry at `platform.yaml: registry`. Grant `artifactregistry.reader` to each
  product project's Cloud Run service agent so it can pull images.
* `platform.yaml: build_project` with Cloud Build enabled. The Drone release SA can submit builds there and push to the registry.
* For GCS-triggered functions: `pubsub.publisher` for the project's GCS service agent
* Secret *containers* (values are set out-of-band; Terraform never sees secret values)

## 6. Repo rules

1. **Product teams edit `product.yaml` and their component folders (code + `deployment.yml`). Nothing else.**
   `deploy/` (incl. `<env>.tfvars.json`), `atlantis.yaml`, `CODEOWNERS`, `pyrightconfig.json` and `platform/schema/` are
   generated by `cdk sync`; the pre-commit hook regenerates them and CI runs `cdk sync --check`.
2. **One component = one folder (`<section>/<name>/`) = one Dockerfile = one Cloud Run resource.** Functions
   included (Functions Framework container), so build, release and promotion work the same for every type.
3. **State is keyed by product name**, not repo path: moving or renaming the folder doesn't orphan state.
4. **Products use the modules from the same commit** (relative path). A module change
   autoplans every product in Atlantis, so the blast radius shows up on the PR.
