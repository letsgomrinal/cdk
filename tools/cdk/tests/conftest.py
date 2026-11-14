"""A throwaway monorepo per test: real platform.yaml + templates, empty products/."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from cdk.model import Repo

REAL_ROOT = Path(__file__).resolve().parents[3]


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copy(REAL_ROOT / "platform.yaml", tmp_path / "platform.yaml")
    shutil.copytree(REAL_ROOT / "platform" / "templates", tmp_path / "platform" / "templates")
    (tmp_path / "products").mkdir()
    for var in ("CDK_BASE", "DRONE_BUILD_EVENT", "DRONE_COMMIT_BEFORE", "DRONE_COMMIT_SHA", "PRODUCTS", "COMPONENTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CDK_ROOT", str(tmp_path))
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    return tmp_path


def quiet(_: str) -> None:
    pass


@pytest.fixture
def orders(root: Path) -> Repo:
    """A product with one component of every kind, committed."""
    from cdk import generate, scaffold

    repo = Repo.load(root)
    adds: list[tuple[str, str, str | None]] = [
        ("app", "storefront", "nextjs"),
        ("api", "backend", None),
        ("job", "nightly", None),
        ("worker", "mailer", None),
        ("function", "ingest", None),
    ]
    scaffold.new_product(repo, "orders", "commerce", ["dev", "prod"], adds, quiet, run_lock=False)
    repo = Repo.load(root)
    generate.sync(repo)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return repo
