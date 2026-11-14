# cdk: serverless products on GCP

A monorepo kit for products made of **web frontends, APIs, background jobs,
worker pools and functions** on Cloud Run. Each product has one
`product.yaml` that lists its components; shared tooling at the repo root
covers everything else (Terraform, Atlantis, Drone, release).

```
$ tools/cdk new orders
Owning team: commerce
Environments [dev,prod]:
Web frontend? (nextjs / react / no) [no]: nextjs
  name [web]: storefront
API backend? (fastapi / no) [no]: fastapi
  name [api]: backend
Background jobs? names, comma-separated [none]: nightly-export, reconcile
Worker pools? names, comma-separated [none]: email-sender
Functions? names, comma-separated [none]:
```

```
$ tools/cdk list
orders  (commerce; envs: dev, prod)  products/orders
  storefront       web       -> service      orders-storefront-svc
  backend          api       -> service      orders-backend-svc
  nightly-export   job       -> job          orders-nightly-export-job
  reconcile        job       -> job          orders-reconcile-job
  email-sender     worker    -> worker-pool  orders-email-sender-wp
```

## Layout

```
platform.yaml               shared settings: org, region, registry, deployers, per-env state bucket + VPC
products/
  orders/
    product.yaml            ← the only file product teams edit for infra
    storefront/  backend/  nightly-export/  …      one folder per component (code + Dockerfile)
    deploy/                 generated: main.tf + backend.<env>.hcl
tools/cdk                   CLI: new / add / remove / list / sync / release / promote
templates/components/       scaffolds: nextjs, react, fastapi, python-job, python-worker, python-function
modules/                    Terraform: product-spec (reads product.yaml) → product → per-type modules
atlantis.yaml               generated: one project per product × env
atlantis/repos.yaml         server-side Atlantis workflow
.drone.yml                  one shared pipeline: checks, release to dev, promote to prod
.cdk/manifest.json          generated inventory used by release
docs/PRODUCT_YAML.md        product.yaml reference
docs/CONVENTIONS.md         naming, IAM, ownership
```

## Day to day

Python tooling uses [uv](https://docs.astral.sh/uv/). `tools/cdk` is a uv script, so its
dependencies install themselves on first run (pinned in `tools/cdk.lock`).

```bash
tools/cdk add orders api search --template fastapi
```

```bash
tools/cdk remove orders reconcile
```

```bash
tools/cdk sync
```

`add` updates `product.yaml`, copies the template into
`products/orders/search/`, runs `uv lock` for Python components, and re-syncs. Edit `product.yaml` by hand whenever
you like, then run `tools/cdk sync`. CI fails if you forget.

## How changes flow

```
edit product.yaml ─► PR ─► Atlantis plans orders-dev, orders-prod ─► approve ─► atlantis apply
edit component code ─► merge ─► Drone: `cdk release dev`  (builds + deploys only changed components)
drone promote <build> prod ─► `cdk promote dev prod`  (deploys the exact images running in dev)
```

* **Nothing is per product.** One Drone pipeline and one Atlantis workflow
  serve every product. `cdk release` maps changed files to components, builds
  each with Cloud Build into `{registry}/{product}/{component}:{sha}`, and
  updates the right Cloud Run resource.
* **Promotion never rebuilds.** It reads the image each workload runs in dev
  and deploys that image to prod. Narrow it with `-p PRODUCTS=orders` or
  `-p COMPONENTS=orders/backend`.
* **Terraform ignores the image**, so infra applies and code releases never
  overwrite each other.

## Python components (uv)

Each Python component is its own uv project (`pyproject.toml` + `uv.lock`) and its
own Docker build, so components don't share a lockfile.

```bash
cd products/orders/backend
```

```bash
uv add httpx
```

```bash
uv run uvicorn main:app --reload
```

The Dockerfile installs with `uv sync --locked --no-dev`, so a stale `uv.lock` fails the
build. CI also checks every lockfile.

## Setup (once, by the platform team)

1. Fill in `platform.yaml`.
2. Create what it references: per-env state buckets, the Artifact Registry
   repo, the `drone-release` SA, per-product projects. See
   [CONVENTIONS.md §5](docs/CONVENTIONS.md#5-who-owns-what).
3. Run Atlantis with `--repo-config=atlantis/repos.yaml`.
4. Add the Drone secret `drone_release_key`.

## Developing the kit

```bash
terraform fmt -recursive
```

```bash
cd modules/product-spec && terraform init -backend=false && terraform test
```

Module tests use a mocked provider and need no GCP access. Requires Terraform
≥ 1.7 for tests (≥ 1.6 to run), google provider ≥ 8.0 (developed against 8.11),
Python ≥ 3.9, uv.
