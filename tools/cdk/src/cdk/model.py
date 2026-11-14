"""The repo as data: platform.yaml, products, components, naming rules."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

PRODUCT_RE = re.compile(r"^[a-z][a-z0-9]{1,9}$")
COMPONENT_RE = re.compile(r"^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$")


@dataclass(frozen=True)
class Kind:
    name: str
    type: str  # Cloud Run resource type
    code: str  # suffix in resource / SA names
    templates: tuple[str, ...]  # first is the default
    language: str


KINDS: dict[str, Kind] = {
    k.name: k
    for k in [
        Kind("web", "service", "svc", ("nextjs", "react"), "node"),
        Kind("api", "service", "svc", ("fastapi",), "python"),
        Kind("job", "job", "job", ("python-job",), "python"),
        Kind("worker", "worker-pool", "wp", ("python-worker",), "python"),
        Kind("function", "function", "fn", ("python-function",), "python"),
    ]
}


class CdkError(Exception):
    """A user-facing error: printed without a traceback."""


def load_yaml(path: Path) -> Any:
    # "safe" = plain dicts/lists, YAML 1.2 (matches Terraform's yamldecode)
    return YAML(typ="safe", pure=True).load(path.read_text())


def find_root(start: Path | None = None) -> Path:
    if env := os.environ.get("CDK_ROOT"):
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / "platform.yaml").exists():
            return d
    raise CdkError("not inside the monorepo (no platform.yaml found in this or any parent directory)")


@dataclass
class Component:
    product: Product
    name: str
    spec: dict[str, Any]

    @property
    def kind(self) -> Kind:
        return KINDS[self.spec["kind"]]

    @property
    def workload(self) -> str:
        return f"{self.product.name}-{self.name}-{self.kind.code}"

    @property
    def path(self) -> Path:
        return self.product.path / self.name

    @property
    def language(self) -> str | None:
        if (self.path / "pyproject.toml").exists():
            return "python"
        if (self.path / "package.json").exists():
            return "node"
        return None

    @property
    def key(self) -> str:
        return f"{self.product.name}/{self.name}"


@dataclass
class Product:
    repo: Repo
    path: Path
    spec: dict[str, Any]
    components: dict[str, Component] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.spec["product"]

    @property
    def team(self) -> str:
        return self.spec["team"]

    @property
    def envs(self) -> list[str]:
        return list(self.spec.get("envs") or [])

    @property
    def region(self) -> str:
        return self.spec.get("region") or self.repo.platform["region"]

    def project(self, env: str) -> str:
        return (self.spec.get("projects") or {}).get(env) or f"{self.repo.platform['org']}-{self.name}-{env}"


@dataclass
class Repo:
    root: Path
    platform: dict[str, Any]
    products: dict[str, Product]

    @property
    def products_dir(self) -> Path:
        return self.root / "products"

    @property
    def templates_dir(self) -> Path:
        return self.root / "platform" / "templates" / "components"

    @property
    def modules_dir(self) -> Path:
        return self.root / "platform" / "terraform" / "modules"

    @property
    def schema_path(self) -> Path:
        return self.root / "platform" / "schema" / "product.schema.json"

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    def components(self) -> list[Component]:
        return [c for p in self.products.values() for c in p.components.values()]

    def product(self, name: str) -> Product:
        if name not in self.products:
            raise CdkError(f"no product '{name}' (have: {', '.join(self.products) or 'none'})")
        return self.products[name]

    @classmethod
    def load(cls, root: Path | None = None, validate: bool = True) -> Repo:
        root = root or find_root()
        platform = load_yaml(root / "platform.yaml")
        repo = cls(root=root, platform=platform, products={})
        for f in sorted((root / "products").glob("*/product.yaml")):
            spec = load_yaml(f) or {}
            if validate:
                from cdk.schema import validate_product

                validate_product(spec, platform, repo.rel(f))
            prod = Product(repo=repo, path=f.parent, spec=spec)
            if prod.name != f.parent.name:
                raise CdkError(f"{repo.rel(f)}: product '{prod.name}' must live in products/{prod.name}/")
            if prod.name in repo.products:
                raise CdkError(f"product '{prod.name}' is defined twice ({repo.rel(f)})")
            prod.components = {
                n: Component(product=prod, name=n, spec=c or {}) for n, c in (spec.get("components") or {}).items()
            }
            repo.products[prod.name] = prod
        return repo
