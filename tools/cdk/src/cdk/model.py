"""The repo as data: platform.yaml, products, components, naming rules."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

DEPLOYMENT_FILE = "deployment.yml"
PRODUCT_RE = re.compile(r"^[a-z][a-z0-9]{1,9}$")
COMPONENT_RE = re.compile(r"^[a-z]([a-z0-9-]{0,13}[a-z0-9])?$")


@dataclass(frozen=True)
class Kind:
    name: str  # singular, used on the CLI: `cdk add orders job nightly`
    section: str  # folder: products/<p>/<section>/<name>/
    type: str  # Cloud Run resource type
    code: str  # suffix in resource / SA names
    templates: tuple[str, ...]  # first is the default
    description: str


# Order here is the order of sections in `cdk list` and the docs.
KINDS: dict[str, Kind] = {
    k.name: k
    for k in [
        Kind("app", "apps", "service", "svc", ("nextjs", "react"), "frontend web app"),
        Kind("api", "apis", "service", "svc", ("fastapi",), "HTTP backend"),
        Kind("job", "jobs", "job", "job", ("python-job",), "run-to-completion task, optionally scheduled"),
        Kind("worker", "workers", "worker-pool", "wp", ("python-worker",), "always-on queue/stream consumer"),
        Kind("function", "functions", "function", "fn", ("python-function",), "event-triggered handler"),
    ]
}
SECTIONS: dict[str, Kind] = {k.section: k for k in KINDS.values()}


class CdkError(Exception):
    """A user-facing error: printed without a traceback."""


LABEL_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
LABEL_VALUE = re.compile(r"^[a-z0-9_-]{0,63}$")
RESERVED_LABELS = ("product", "workload", "workload-type", "env", "team", "managed-by")


def validate_platform(platform: dict[str, Any]) -> None:
    errors = [f"missing '{k}'" for k in ("org", "region", "team", "envs", "registry", "build_project")
              if not platform.get(k)]  # fmt: skip
    for k, v in (platform.get("labels") or {}).items():
        if not LABEL_KEY.match(str(k)) or not LABEL_VALUE.match(str(v)):
            errors.append(f"labels.{k}: GCP labels are lowercase [a-z0-9_-], keys start with a letter, max 63 chars")
        if k in RESERVED_LABELS:
            errors.append(f"labels.{k}: reserved, set automatically")
    if errors:
        raise CdkError("platform.yaml:\n  - " + "\n  - ".join(errors))


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
    kind: Kind
    name: str
    spec: dict[str, Any]

    @property
    def workload(self) -> str:
        return f"{self.product.name}-{self.name}-{self.kind.code}"

    @property
    def path(self) -> Path:
        return self.product.path / self.kind.section / self.name

    @property
    def config_file(self) -> Path:
        return self.path / DEPLOYMENT_FILE

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
    """A folder under products/. Everything product-level comes from platform.yaml."""

    repo: Repo
    path: Path
    components: dict[str, Component] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def team(self) -> str:
        return self.repo.platform["team"]

    @property
    def envs(self) -> list[str]:
        return list(self.repo.platform["envs"])

    @property
    def region(self) -> str:
        return self.repo.platform["region"]

    def project(self, env: str) -> str:
        return f"{self.repo.platform['org']}-{self.name}-{env}"


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
    def schema_dir(self) -> Path:
        return self.root / "platform" / "schema"

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
        if validate:
            validate_platform(platform)
        # Every folder under products/ is a product (files like README.md are ignored).
        for d in sorted(p for p in (root / "products").glob("[!.]*") if p.is_dir()):
            if not PRODUCT_RE.match(d.name):
                raise CdkError(f"products/{d.name}: product names are 2-10 chars, [a-z][a-z0-9]*, no hyphens")
            prod = Product(repo=repo, path=d)
            # The folders are the registry: <section>/<name>/deployment.yml is a component.
            for kind in KINDS.values():
                for c in sorted(p for p in (prod.path / kind.section).glob("[!.]*") if p.is_dir()):
                    where = repo.rel(c / DEPLOYMENT_FILE)
                    if not (c / DEPLOYMENT_FILE).exists():
                        raise CdkError(f"{repo.rel(c)}/ has no {DEPLOYMENT_FILE} (create one, or `cdk add`)")
                    if not COMPONENT_RE.match(c.name):
                        raise CdkError(f"{repo.rel(c)}: component names are 1-15 chars, [a-z0-9-], start with a letter")
                    if c.name in prod.components:
                        other = prod.components[c.name].kind.section
                        raise CdkError(f"'{c.name}' exists in both {other}/ and {kind.section}/; names must be unique")
                    doc = load_yaml(c / DEPLOYMENT_FILE)
                    if validate:
                        from cdk.schema import validate_deployment

                        validate_deployment(doc, kind, platform, where)
                    prod.components[c.name] = Component(product=prod, kind=kind, name=c.name, spec=doc or {})
            repo.products[prod.name] = prod
        return repo
