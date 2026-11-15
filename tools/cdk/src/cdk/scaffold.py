"""new / add / remove: create products and components from templates."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from cdk.model import COMPONENT_RE, KINDS, PRODUCT_RE, CdkError, Repo

Log = Callable[[str], None]

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


def copy_template(
    repo: Repo, product: str, section: str, name: str, template: str, log: Log, run_lock: bool = True
) -> None:
    src = repo.templates_dir / template
    dst = repo.products_dir / product / section / name
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

    prod_dir = repo.products_dir / product
    if not prod_dir.is_dir():
        raise CdkError(f"no product '{product}'; create it with `cdk new {product}`")
    for k in KINDS.values():
        if (prod_dir / k.section / name).exists():
            raise CdkError(f"{product} already has a component named '{name}' (in {k.section}/)")
    copy_template(repo, product, KINDS[kind].section, name, template, log, run_lock)


def new_product(
    repo: Repo, product: str, adds: list[tuple[str, str, str | None]], log: Log, run_lock: bool = True
) -> None:
    """A product is just a folder; it gets its deploy/ files from `cdk sync`."""
    if not PRODUCT_RE.match(product):
        raise CdkError("product must be 2-10 chars, [a-z][a-z0-9]*, no hyphens (it prefixes every SA name)")
    if product in repo.products or (repo.products_dir / product).exists():
        raise CdkError(f"product '{product}' already exists")
    d = repo.products_dir / product
    d.mkdir(parents=True)
    log(f"  create {repo.rel(d)}/")
    for kind, name, template in adds:
        add_component(repo, product, kind, name, template, log, run_lock)


def remove_component(repo: Repo, product: str, name: str, keep_code: bool, log: Log) -> list[str]:
    """Returns notes for the user (leftover overrides, deletion protection)."""
    prod = repo.product(product)
    if name not in prod.components:
        raise CdkError(f"{product} has no component '{name}' (have: {', '.join(prod.components) or 'none'})")
    comp = prod.components[name]
    if keep_code:
        comp.config_file.unlink()
        log(f"  delete {repo.rel(comp.config_file)}  (code kept)")
    else:
        shutil.rmtree(comp.path)
        log(f"  delete {repo.rel(comp.path)}/")

    notes = []
    protected = [e for e in prod.envs if repo.platform["envs"][e].get("deletion_protection", True)]
    if protected:
        notes.append(
            f"Deletion protection is on in {', '.join(protected)}: the Atlantis apply there will refuse to delete "
            "the Cloud Run resource until protection is lifted for that apply (ask the platform team)."
        )
    return notes
