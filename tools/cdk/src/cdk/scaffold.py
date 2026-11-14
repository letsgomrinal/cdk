"""new / add / remove: create products and components from templates."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from cdk.model import COMPONENT_RE, KINDS, PRODUCT_RE, CdkError, Repo, load_yaml
from cdk.yamledit import delete_component, insert_component

Log = Callable[[str], None]

PRODUCT_HEADER = """\
# yaml-language-server: $schema=../../platform/schema/product.schema.json
#
# Infra for product "{product}". This file is the whole definition:
# add/remove components here (or with `cdk add|remove`), then run `cdk sync`.
# Reference: docs/PRODUCT_YAML.md
product: {product}
team: {team}
envs: [{envs}]

components: {{}}

# Per-env tweaks, shallow-merged into a component's settings:
# overrides:
#   prod:
#     backend: {{ min_instances: 2, memory: 1Gi }}
"""

SNIPPETS = {
    "web": """\
kind: web
template: {template}
public: true          # internet-facing; delete this line to keep it internal
# calls: [backend]    # may invoke `backend`; its URL is injected as BACKEND_URL
""",
    "api": """\
kind: api
template: {template}
# secret_env: {{ DB_URL: {product}-db-url }}    # access to the secret is granted automatically
# access: {{ publish: [{product}-events] }}
""",
    "job": """\
kind: job
template: {template}
# schedules:
#   daily: {{ cron: "0 2 * * *", time_zone: Etc/UTC }}
# access: {{ buckets: {{ "{org}-{product}-exports-{{env}}": write }} }}
""",
    "worker": """\
kind: worker
template: {template}
instances: 1
# env: {{ SUBSCRIPTION: "projects/{{project}}/subscriptions/{product}-{name}" }}
# access: {{ subscribe: [{product}-{name}] }}
""",
    "function": """\
kind: function
template: {template}
# triggers:
#   upload:
#     event_type: google.cloud.storage.object.v1.finalized
#     filters: {{ bucket: "{org}-{product}-inbox-{{env}}" }}
""",
}

LOCKERS: dict[str, list[str]] = {
    "python": ["uv", "lock", "--quiet"],
    "node": ["pnpm", "install", "--lockfile-only", "--silent"],
}


def lock(path: Path, language: str, repo: Repo, log: Log) -> None:
    """Create the component's lockfile (uv.lock / pnpm-lock.yaml); Docker builds require it."""
    cmd = LOCKERS[language]
    if not shutil.which(cmd[0]):
        log(f"  warn   {cmd[0]} not found: run `{' '.join(cmd[:2])}` in {repo.rel(path)}/ before the first build")
        return
    res = subprocess.run(cmd, cwd=path, capture_output=True, text=True, check=False)
    if res.returncode:
        log(f"  warn   `{' '.join(cmd)}` failed in {repo.rel(path)}/:\n{res.stderr.strip()}")
    else:
        log(f"  lock   {repo.rel(path)}/")


def copy_template(repo: Repo, product: str, name: str, template: str, log: Log, run_lock: bool = True) -> None:
    src = repo.templates_dir / template
    dst = repo.products_dir / product / name
    if dst.exists():
        log(f"  keep   {repo.rel(dst)}/ (already exists)")
        return
    shutil.copytree(src, dst)
    for f in dst.rglob("*"):
        if not f.is_file():
            continue
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        f.write_text(text.replace("__PRODUCT__", product).replace("__NAME__", name))
    log(f"  create {repo.rel(dst)}/  ({template})")
    lang = "python" if (dst / "pyproject.toml").exists() else "node" if (dst / "package.json").exists() else None
    if lang and run_lock:
        lock(dst, lang, repo, log)


def add_component(
    repo: Repo, product: str, kind: str, name: str, template: str | None, log: Log, run_lock: bool = True
) -> None:
    if kind not in KINDS:
        raise CdkError(f"unknown kind '{kind}', pick one of: {', '.join(KINDS)}")
    templates = KINDS[kind].templates
    template = template or templates[0]
    if template not in templates:
        raise CdkError(f"template '{template}' isn't available for {kind} (choose: {', '.join(templates)})")
    if not COMPONENT_RE.match(name):
        raise CdkError(f"component name '{name}' must be 1-15 chars, [a-z0-9-], starting with a letter")

    path = repo.products_dir / product / "product.yaml"
    if not path.exists():
        raise CdkError(f"no product '{product}'; create it with `cdk new {product}`")
    spec = load_yaml(path) or {}
    if name in (spec.get("components") or {}):
        raise CdkError(f"{product} already has a component named '{name}'")

    snippet = SNIPPETS[kind].format(template=template, product=product, name=name, org=repo.platform["org"])
    text = insert_component(path.read_text(), name, snippet)
    path.write_text(text)
    if name not in (load_yaml(path).get("components") or {}):
        raise CdkError(f"couldn't place '{name}' in {repo.rel(path)}; add it under components: by hand")
    log(f"  update {repo.rel(path)}  (+ {name}: {kind})")
    copy_template(repo, product, name, template, log, run_lock)


def new_product(
    repo: Repo,
    product: str,
    team: str,
    envs: list[str],
    adds: list[tuple[str, str, str | None]],
    log: Log,
    run_lock: bool = True,
) -> None:
    if not PRODUCT_RE.match(product):
        raise CdkError("product must be 2-10 chars, [a-z][a-z0-9]*, no hyphens (it prefixes every SA name)")
    if product in repo.products or (repo.products_dir / product).exists():
        raise CdkError(f"product '{product}' already exists")
    if not team:
        raise CdkError("a team is required")
    for e in envs:
        if e not in repo.platform["envs"]:
            raise CdkError(f"env '{e}' isn't in platform.yaml (have: {', '.join(repo.platform['envs'])})")
    d = repo.products_dir / product
    d.mkdir(parents=True)
    (d / "product.yaml").write_text(PRODUCT_HEADER.format(product=product, team=team, envs=", ".join(envs)))
    log(f"  create {repo.rel(d / 'product.yaml')}")
    for kind, name, template in adds:
        add_component(repo, product, kind, name, template, log, run_lock)


def remove_component(repo: Repo, product: str, name: str, keep_code: bool, log: Log) -> list[str]:
    """Returns notes for the user (leftover overrides, deletion protection)."""
    prod = repo.product(product)
    path = prod.path / "product.yaml"
    if name not in prod.components:
        raise CdkError(f"{product} has no component '{name}' (have: {', '.join(prod.components) or 'none'})")
    text = delete_component(path.read_text(), name)
    if text is None:
        raise CdkError(f"couldn't find '  {name}:' under components: in {repo.rel(path)}; remove it by hand")
    path.write_text(text)
    log(f"  update {repo.rel(path)}  (- {name})")
    code = prod.path / name
    if code.exists() and not keep_code:
        shutil.rmtree(code)
        log(f"  delete {repo.rel(code)}/")

    notes = []
    leftover = [e for e, o in (prod.spec.get("overrides") or {}).items() if o and name in o]
    if leftover:
        notes.append(f"Also remove overrides for '{name}' under: {', '.join('overrides.' + e for e in leftover)}")
    protected = [e for e in prod.envs if repo.platform["envs"][e].get("deletion_protection", True)]
    if protected:
        notes.append(
            f"Deletion protection is on in {', '.join(protected)}: the Atlantis apply there will refuse to delete "
            "the Cloud Run resource until protection is lifted for that apply (ask the platform team)."
        )
    return notes
