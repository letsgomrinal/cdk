"""`cdk check`: lint, type-check and test components (all, or only affected ones).

Python  uv lock --check, ruff check + format --check, basedpyright, pytest (if tests/)
Node    pnpm install --frozen-lockfile, biome check, pnpm build (with --build)
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from cdk.model import Component, Repo

Log = Callable[[str], None]


@dataclass
class Result:
    component: Component
    step: str
    ok: bool
    output: str
    seconds: float


def _steps(c: Component, build: bool) -> list[tuple[str, list[str]]]:
    d = str(c.path)
    if c.language == "python":
        steps = [
            ("lockfile", ["uv", "lock", "--check", "--quiet", "--directory", d]),
            ("install", ["uv", "sync", "--locked", "--quiet", "--directory", d]),
            ("ruff", ["ruff", "check", d]),
            ("format", ["ruff", "format", "--check", d]),
            ("types", ["basedpyright", d]),  # pyrightconfig.json maps d to d/.venv
        ]
        if (c.path / "tests").is_dir():
            steps.append(("tests", ["uv", "run", "--locked", "--directory", d, "pytest", "-q"]))
        return steps
    if c.language == "node":
        steps = [
            ("install", ["pnpm", "install", "--frozen-lockfile", "--silent", "--dir", d]),
            ("biome", ["pnpm", "exec", "biome", "check", d]),
        ]
        if build:
            steps.append(("build", ["pnpm", "--dir", d, "build"]))
        return steps
    return []


def check(repo: Repo, comps: list[Component], log: Log, *, language: str | None = None, build: bool = False,
          fail_fast: bool = False) -> list[Result]:  # fmt: skip
    results: list[Result] = []
    for c in comps:
        if language and c.language != language:
            continue
        steps = _steps(c, build)
        if not steps:
            log(f"{c.key}: no pyproject.toml or package.json, skipped")
            continue
        for name, cmd in steps:
            if not shutil.which(cmd[0]):
                results.append(Result(c, name, False, f"{cmd[0]} not found (run `mise install`)", 0))
                break
            t = time.monotonic()
            res = subprocess.run(cmd, cwd=repo.root, capture_output=True, text=True, check=False)
            r = Result(c, name, res.returncode == 0, (res.stdout + res.stderr).strip(), time.monotonic() - t)
            results.append(r)
            log(f"  {'ok  ' if r.ok else 'FAIL'} {c.key:28} {name:9} {r.seconds:5.1f}s")
            if not r.ok:
                log("\n".join("       " + line for line in r.output.splitlines()[-30:]))
                break  # later steps depend on earlier ones
        if fail_fast and any(not r.ok for r in results):
            break
    return results
