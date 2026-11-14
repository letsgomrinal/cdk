"""Which components does a change touch?

Two scopes:
  release  only components whose own folder changed (code to rebuild and deploy)
  check    also every component when shared lint/test config changes, since
           components that passed before may fail now
"""

from __future__ import annotations

import os
import subprocess
from typing import Literal

from cdk.model import Component, Repo

Scope = Literal["release", "check"]

# Changes here can change the result of checking any component.
SHARED_CONFIG = (
    "pyproject.toml",
    "uv.lock",
    "biome.json",
    "package.json",
    "pnpm-workspace.yaml",
    "pnpm-lock.yaml",
    "tools/",
)


def _git(repo: Repo, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo.root), *args], capture_output=True, text=True, check=False)


def resolve_base(repo: Repo, explicit: str | None = None) -> str | None:
    """Explicit > $CDK_BASE > PR target branch (Drone) > $DRONE_COMMIT_BEFORE."""
    if explicit:
        return explicit
    if base := os.environ.get("CDK_BASE"):
        return base
    if os.environ.get("DRONE_BUILD_EVENT") == "pull_request" and (target := os.environ.get("DRONE_TARGET_BRANCH")):
        _git(repo, "fetch", "--quiet", "origin", target)
        res = _git(repo, "merge-base", "HEAD", f"origin/{target}")
        if res.returncode == 0:
            return res.stdout.strip()
    return os.environ.get("DRONE_COMMIT_BEFORE")


def changed_files(repo: Repo, base: str | None) -> list[str] | None:
    """Files changed between base and HEAD (plus uncommitted). None = unknown, treat as everything."""
    if not base or set(base) == {"0"}:
        return None
    if _git(repo, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
        return None
    committed = _git(repo, "diff", "--name-only", f"{base}...HEAD")
    if committed.returncode != 0:
        return None
    local = _git(repo, "status", "--porcelain", "--untracked-files=all")
    files = set(committed.stdout.split())
    files |= {line[3:].split(" -> ")[-1] for line in local.stdout.splitlines() if line.strip()}
    return sorted(files)


def owns(comp: Component, path: str) -> bool:
    prefix = comp.product.repo.rel(comp.path)
    return path == prefix or path.startswith(prefix + "/")


def affected(repo: Repo, files: list[str] | None, scope: Scope) -> list[Component]:
    comps = repo.components()
    if files is None:
        return comps
    if scope == "check" and any(f == s or (s.endswith("/") and f.startswith(s)) for f in files for s in SHARED_CONFIG):
        return comps
    return [c for c in comps if any(owns(c, f) for f in files)]
