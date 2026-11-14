# Developing in this repo

## Setup (once)

```bash
curl https://mise.run | sh
```

```bash
mise install && mise run setup
```

[mise](https://mise.jdx.dev) installs the exact tool versions from `mise.toml`
(Python, uv, Node, pnpm, Terraform, tflint, lefthook) and puts `.venv/bin`
on your PATH, so `cdk` works from anywhere in the repo. `mise run setup` runs
`uv sync`, `pnpm install`, installs tflint plugins and the git hooks.

In VS Code, accept the recommended extensions. Formatting on save, the
`product.yaml` schema and per-component type checking are already configured.

## Tooling

| Area | Tool | Config |
|---|---|---|
| Toolchain, tasks | mise | `mise.toml` |
| Python deps | uv: one workspace for `cdk` + dev tools; one project per component | `pyproject.toml`, `*/uv.lock` |
| Python lint/format | ruff | `[tool.ruff]` in `pyproject.toml` |
| Python types | basedpyright | `pyrightconfig.json` (generated: maps each component to its own `.venv`) |
| Python tests | pytest | `[tool.pytest.ini_options]`, component `tests/` |
| JS deps | pnpm workspace, one lockfile per component | `pnpm-workspace.yaml` |
| JS lint/format | biome | `biome.json` |
| Terraform | `terraform fmt`, `terraform test` (mocked provider), tflint | `.tflint.hcl` |
| product.yaml | JSON Schema | `platform/schema/product.schema.json` (generated) |
| Git hooks | lefthook | `lefthook.yml` |
| Dependency updates | Renovate | `renovate.json` |
| Ownership | CODEOWNERS | generated from each product's `team` |

### Why one lockfile per component?

Each component is its own Docker build (`gcloud builds submit products/<p>/<c>`),
and a Docker build can only see files inside its folder. So every component
carries its own `uv.lock` or `pnpm-lock.yaml`. Shared *config* (ruff, biome,
basedpyright) lives once at the root, and the pnpm store and uv cache are shared.

## Git hooks

| Hook | Does |
|---|---|
| pre-commit | ruff fix + format, biome fix + format, `terraform fmt` on staged files (fixes are re-staged); `cdk sync` when `product.yaml`/`platform.yaml` change; lockfile + checks for components whose dependencies changed |
| pre-push | `cdk check --affected` against `origin/main`; `pytest` if `tools/cdk` changed |

Skip once with `LEFTHOOK=0 git commit …`. CI runs the same checks either way.

## What CI runs (`.drone.yml`)

| Step | Image | Runs |
|---|---|---|
| terraform | `hashicorp/terraform` | fmt check, module tests |
| tflint | `tflint` | lint modules (Google ruleset) |
| python | `uv` | ruff, basedpyright, pytest for `cdk`, `cdk sync --check` |
| python-components | `uv` | `cdk check --affected --lang python` |
| node-components | `node` | biome, `cdk check --affected --lang node --build` |
| release / promote | `google-cloud-cli` | `cdk release dev` on main, `cdk promote dev prod` on promote |

Affected means components whose folder changed since the PR's merge base
(or the previous commit on main). A change to shared config (`pyproject.toml`,
`biome.json`, lockfiles at the root, `tools/`) checks every component.

## Working on `cdk` itself

```bash
uv run pytest
```

```bash
uv run basedpyright && uv run ruff check .
```

Modules: `tools/cdk/src/cdk/`. `model` is the repo model, `schema` the
product.yaml schema, `yamledit` handles comment-safe edits, `scaffold` is
new/add/remove, `generate` is sync, `affected` and `check` are CI, and
`release` is release/promote. Tests build a throwaway repo per test
(`tests/conftest.py`).

When you add a `product.yaml` key, add it to `TYPE_KEYS` in `schema.py` **and**
`allowed_keys` in `platform/terraform/modules/product-spec/main.tf`.
`test_schema_matches_terraform_allowed_keys` fails until both agree.
