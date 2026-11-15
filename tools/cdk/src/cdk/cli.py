"""cdk: the monorepo CLI.

cdk new <product>                    interactive: pick apps / apis / jobs / workers / functions
cdk new <product> --team T --add app:storefront:nextjs --add job:nightly-export
cdk add <product> <kind> <name> [--template T]
cdk remove <product> <name> [--keep-code] [-y]
cdk list
cdk sync [--check]                   regenerate deploy/, atlantis.yaml, CODEOWNERS, product schema
cdk affected [--base REV] [--json]   components touched by a change
cdk check [--affected] [--lang python|node] [--build]
cdk release <env> [--products a,b] [--components p/c] [--since REV | --all] [--dry-run]
cdk promote <from-env> <to-env> [--products a,b] [--components p/c] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys

from cdk import affected as aff
from cdk import check as chk
from cdk import generate, release, scaffold
from cdk.model import KINDS, CdkError, Repo


def log(msg: str) -> None:
    print(msg, flush=True)


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        return input(f"{prompt}{suffix}: ").strip() or default
    except EOFError:
        return default


def _sync(repo_root_hint: Repo) -> None:
    repo = Repo.load(repo_root_hint.root)
    for path in generate.sync(repo):
        log(f"  sync   {path}")


def cmd_new(a: argparse.Namespace) -> None:
    repo = Repo.load()
    adds: list[tuple[str, str, str | None]] = []
    for spec in a.add or []:
        parts = spec.split(":")
        if len(parts) not in (2, 3):
            raise CdkError(f"--add expects kind:name[:template], got {spec}")
        adds.append((parts[0], parts[1], parts[2] if len(parts) == 3 else None))
    if not adds and sys.stdin.isatty():
        log(f"New product '{a.product}'. Press enter to skip a question.\n")
        app = ask("Frontend app? (nextjs / react / no)", "no")
        if app != "no":
            adds.append(("app", ask("  name", "web"), app))
        api = ask("API backend? (fastapi / no)", "no")
        if api != "no":
            adds.append(("api", ask("  name", "api"), api))
        for kind, label in [("job", "Background jobs"), ("worker", "Worker pools"), ("function", "Functions")]:
            names = ask(f"{label}? names, comma-separated", "none")
            if names != "none":
                adds += [(kind, n.strip(), None) for n in names.split(",") if n.strip()]

    scaffold.new_product(repo, a.product, adds, log, run_lock=not a.no_lock)
    _sync(repo)
    log(f"\nNext: review the deployment.yml files in products/{a.product}/, commit, and open a PR (Atlantis plans it).")


def cmd_add(a: argparse.Namespace) -> None:
    repo = Repo.load()
    scaffold.add_component(repo, a.product, a.kind, a.name, a.template, log, run_lock=not a.no_lock)
    _sync(repo)


def cmd_remove(a: argparse.Namespace) -> None:
    repo = Repo.load()
    prod = repo.product(a.product)
    comp = prod.components.get(a.name)
    if comp and not a.yes:
        what = f"{comp.key}" + (" (keeps the code)" if a.keep_code else f" (deletes {repo.rel(comp.path)}/)")
        if ask(f"Remove {what}? (y/N)", "n").lower() != "y":
            raise CdkError("aborted")
    notes = scaffold.remove_component(repo, a.product, a.name, a.keep_code, log)
    _sync(repo)
    for n in notes:
        log(f"\nNote: {n}")


def cmd_list(_: argparse.Namespace) -> None:
    repo = Repo.load()
    for p in repo.products.values():
        log(f"{p.name}  {repo.rel(p.path)}  ({len(p.components)} components)")
        for c in p.components.values():
            log(f"  {c.kind.section + '/' + c.name:26} {c.kind.type:12} {c.workload}")


def cmd_config(a: argparse.Namespace) -> None:
    from io import StringIO

    from ruamel.yaml import YAML

    from cdk.compile import compile_component, resolve

    repo = Repo.load()
    product, _, name = a.component.partition("/")
    prod = repo.product(product)
    if name not in prod.components:
        raise CdkError(f"{product} has no component '{name}' (have: {', '.join(prod.components) or 'none'})")
    comp = prod.components[name]
    env = a.env or prod.envs[0]
    if env not in prod.envs:
        raise CdkError(f"{product} has no env '{env}' (have: {', '.join(prod.envs)})")
    errors: list[str] = []
    doc = compile_component(comp, env, errors) if a.compiled else resolve(comp, env)
    if errors:
        raise CdkError("\n".join(errors))
    y = YAML()
    y.default_flow_style = False
    buf = StringIO()
    y.dump(doc, buf)
    what = "Terraform input" if a.compiled else "effective deployment.yml"
    log(f"# {comp.key} ({comp.kind.name} -> Cloud Run {comp.kind.type}), {what} for {env}\n{buf.getvalue()}")


def cmd_sync(a: argparse.Namespace) -> None:
    repo = Repo.load()
    changed = generate.sync(repo, check=a.check)
    if a.check:
        if changed:
            raise CdkError("generated files are out of date, run `cdk sync`:\n  " + "\n  ".join(changed))
        log("generated files are up to date")
    else:
        for path in changed:
            log(f"  sync   {path}")


def cmd_affected(a: argparse.Namespace) -> None:
    repo = Repo.load()
    base = aff.resolve_base(repo, a.base)
    files = aff.changed_files(repo, base)
    comps = aff.affected(repo, files, a.scope)
    if a.json:
        print(json.dumps({"base": base, "all": files is None, "components": [c.key for c in comps]}, indent=2))
        return
    if files is None:
        log("no usable base commit: everything is affected")
    for c in comps:
        log(c.key)


def cmd_check(a: argparse.Namespace) -> None:
    repo = Repo.load()
    comps = repo.components()
    if a.affected:
        base = aff.resolve_base(repo, a.base)
        files = aff.changed_files(repo, base)
        comps = aff.affected(repo, files, "check")
        log(f"checking {len(comps)} affected component(s)" + (" (no usable base: all)" if files is None else ""))
    results = chk.check(repo, comps, log, language=a.lang, build=a.build, fail_fast=a.fail_fast)
    failed = sorted({r.component.key for r in results if not r.ok})
    if failed:
        raise CdkError(f"checks failed: {', '.join(failed)}")
    log(f"all checks passed ({len({r.component.key for r in results})} component(s))")


def cmd_release(a: argparse.Namespace) -> None:
    release.release(Repo.load(), a.env, log, products=a.products, components=a.components, since=a.since,
                    all_=a.all, build=not a.no_build, dry_run=a.dry_run)  # fmt: skip


def cmd_promote(a: argparse.Namespace) -> None:
    release.promote(Repo.load(), a.from_env, a.to_env, log, products=a.products, components=a.components,
                    dry_run=a.dry_run)  # fmt: skip


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cdk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create a product (interactive without flags)")
    p.add_argument("product")
    p.add_argument("--add", action="append", metavar="KIND:NAME[:TEMPLATE]", help=f"kinds: {', '.join(KINDS)}")
    p.add_argument("--no-lock", action="store_true", help="don't run uv lock / pnpm install")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("add", help="add a component to a product")
    p.add_argument("product")
    p.add_argument("kind", choices=list(KINDS), help="; ".join(f"{k.name}: {k.description}" for k in KINDS.values()))
    p.add_argument("name")
    p.add_argument("--template", help="; ".join(f"{k}: {'|'.join(v.templates)}" for k, v in KINDS.items()))
    p.add_argument("--no-lock", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("remove", help="remove a component from a product")
    p.add_argument("product")
    p.add_argument("name")
    p.add_argument("--keep-code", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(fn=cmd_remove)

    sub.add_parser("list", help="list products and components").set_defaults(fn=cmd_list)

    p = sub.add_parser("config", help="show a component's effective config for an env")
    p.add_argument("component", metavar="PRODUCT/COMPONENT")
    p.add_argument("--env", help="default: the product's first env")
    p.add_argument("--compiled", action="store_true", help="show what Terraform receives instead")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("sync", help="regenerate generated files")
    p.add_argument("--check", action="store_true", help="fail if anything is out of date (CI, git hook)")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("affected", help="components touched by changes since a base commit")
    p.add_argument("--base", help="default: $CDK_BASE, PR target branch, or $DRONE_COMMIT_BEFORE")
    p.add_argument("--scope", choices=["check", "release"], default="check")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_affected)

    p = sub.add_parser("check", help="lint, type-check and test components")
    p.add_argument("--affected", action="store_true", help="only components affected since --base")
    p.add_argument("--base")
    p.add_argument("--lang", choices=["python", "node"])
    p.add_argument("--build", action="store_true", help="also build node components")
    p.add_argument("--fail-fast", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("release", help="build changed components and deploy them to an env")
    p.add_argument("env")
    p.add_argument("--products", help="default: $PRODUCTS")
    p.add_argument("--components", help="product/component or component, comma-separated (default: $COMPONENTS)")
    p.add_argument("--since", help="base commit (default: $DRONE_COMMIT_BEFORE)")
    p.add_argument("--all", action="store_true", help="ignore changes, release everything")
    p.add_argument("--no-build", action="store_true", help="deploy the already-built image for this commit")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_release)

    p = sub.add_parser("promote", help="deploy the images running in one env to another")
    p.add_argument("from_env")
    p.add_argument("to_env")
    p.add_argument("--products", help="default: $PRODUCTS, else all")
    p.add_argument("--components")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_promote)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.fn(args)
    except CdkError as e:
        print(f"cdk: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # e.g. `cdk list | head`
        sys.stderr.close()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
