"""release / promote: build changed components and roll them out with gcloud.

Terraform (via Atlantis) creates resources and ignores the container image;
this module only changes the image.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from typing import Any

from cdk.affected import affected, changed_files, resolve_base
from cdk.model import CdkError, Component, Repo

Log = Callable[[str], None]
PLACEHOLDER_IMAGES = "us-docker.pkg.dev/cloudrun/container/"

GCLOUD = {
    "service": ["gcloud", "run", "services"],
    "function": ["gcloud", "run", "services"],
    "job": ["gcloud", "run", "jobs"],
    "worker-pool": ["gcloud", "beta", "run", "worker-pools"],
}


class Runner:
    def __init__(self, log: Log, dry_run: bool) -> None:
        self.log = log
        self.dry_run = dry_run
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], capture: bool = False) -> str:
        self.commands.append(cmd)
        self.log("  $ " + " ".join(cmd))
        if self.dry_run:
            return ""
        res = subprocess.run(cmd, check=True, text=True, capture_output=capture)
        return res.stdout if capture else ""


def deploy_cmd(comp: Component, env: str, image: str) -> list[str]:
    verb = "deploy" if comp.kind.type == "worker-pool" else "update"
    prod = comp.product
    return [*GCLOUD[comp.kind.type], verb, comp.workload, "--image", image,
            "--project", prod.project(env), "--region", prod.region, "--quiet"]  # fmt: skip


def image_ref(comp: Component, sha: str) -> str:
    return f"{comp.product.repo.platform['registry']}/{comp.product.name}/{comp.name}:{sha[:12]}"


def first_container_image(node: Any) -> str | None:
    """Find containers[0].image anywhere in a gcloud describe JSON (shape differs per resource)."""
    if isinstance(node, dict):
        containers = node.get("containers")
        if isinstance(containers, list) and containers and isinstance(containers[0], dict):
            return containers[0].get("image")
        node = list(node.values())
    if isinstance(node, list):
        for v in node:
            if found := first_container_image(v):
                return found
    return None


def select(repo: Repo, env: str, products: list[str], components: list[str]) -> list[Component]:
    for p in products:
        repo.product(p)  # raises on unknown
    out = []
    for c in repo.components():
        if env not in c.product.envs:
            continue
        if products and c.product.name not in products:
            continue
        if components and c.key not in components and c.name not in components:
            continue
        out.append(c)
    return out


def _env_list(arg: str | None, var: str) -> list[str]:
    return [x for x in (arg or os.environ.get(var, "")).split(",") if x]


def release(
    repo: Repo, env: str, log: Log, *, products: str | None = None, components: str | None = None,
    since: str | None = None, all_: bool = False, build: bool = True, dry_run: bool = False,
) -> Runner:  # fmt: skip
    prods, comps = _env_list(products, "PRODUCTS"), _env_list(components, "COMPONENTS")
    targets = select(repo, env, prods, comps)
    if not (all_ or prods or comps):
        base = resolve_base(repo, since)
        files = changed_files(repo, base)
        if files is None:
            log("no usable base commit: releasing every component")
        else:
            log(f"changed since {base[:12] if base else '?'}: {len(files)} file(s)")
            in_scope = {c.key for c in affected(repo, files, "release")}
            targets = [c for c in targets if c.key in in_scope]

    run = Runner(log, dry_run)
    if not targets:
        log(f"nothing to release to {env}")
        return run
    sha = (
        os.environ.get("DRONE_COMMIT_SHA")
        or subprocess.run(
            ["git", "-C", str(repo.root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    for c in targets:
        image = image_ref(c, sha)
        log(f"\n== {c.key} ({c.kind.name}) -> {c.workload} in {c.product.project(env)}")
        if build:
            run(["gcloud", "builds", "submit", repo.rel(c.path), "--tag", image,
                 "--project", repo.platform["build_project"], "--quiet"])  # fmt: skip
        run(deploy_cmd(c, env, image))
    return run


def promote(
    repo: Repo, from_env: str, to_env: str, log: Log, *, products: str | None = None,
    components: str | None = None, dry_run: bool = False,
) -> Runner:  # fmt: skip
    if from_env not in repo.platform["envs"] or to_env not in repo.platform["envs"]:
        raise CdkError(f"envs must be among: {', '.join(repo.platform['envs'])}")
    run = Runner(log, dry_run)
    for c in select(repo, to_env, _env_list(products, "PRODUCTS"), _env_list(components, "COMPONENTS")):
        if from_env not in c.product.envs:
            continue
        log(f"\n== {c.key}: {from_env} -> {to_env}")
        prod = c.product
        out = run([*GCLOUD[c.kind.type], "describe", c.workload, "--project", prod.project(from_env),
                   "--region", prod.region, "--format=json"], capture=True)  # fmt: skip
        image = "<image running in " + from_env + ">" if dry_run else first_container_image(json.loads(out))
        if not image or image.startswith(PLACEHOLDER_IMAGES):
            log(f"  skip: never released to {from_env}")
            continue
        run(deploy_cmd(c, to_env, image))
    return run
