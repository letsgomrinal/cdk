"""Compile product.yaml + platform.yaml + every deployment.yml into one Terraform input per env.

    resolve(component, env)  -> the component's effective deployment.yml for that env
                                (environments.<env> deep-merged, placeholders filled in)
    compile_product(p, env)  -> {"config": {...}}, written to deploy/<env>.tfvars.json

The output matches the variables of platform/terraform/modules/product. Keys
the user didn't set are left out, so the module's defaults apply.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from cdk.model import CdkError, Component, Product

INGRESS = {
    "internal": "INGRESS_TRAFFIC_INTERNAL_ONLY",
    "load-balancer": "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER",
    "all": "INGRESS_TRAFFIC_ALL",
}
EGRESS = {"private-ranges": "PRIVATE_RANGES_ONLY", "all-traffic": "ALL_TRAFFIC", "none": "NONE"}
EXEC_ENV = {"gen1": "EXECUTION_ENVIRONMENT_GEN1", "gen2": "EXECUTION_ENVIRONMENT_GEN2"}
MODULE_INPUT = {"service": "services", "job": "jobs", "worker-pool": "worker_pools", "function": "functions"}


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Dicts merge recursively; anything else (lists, scalars) is replaced."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else copy.deepcopy(v)
    return out


def _fill(node: Any, values: dict[str, str]) -> Any:
    if isinstance(node, str):
        return re.sub(r"\{(env|project|product)\}", lambda m: values[m.group(1)], node)
    if isinstance(node, dict):
        return {_fill(k, values): _fill(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, values) for v in node]
    return node


def resolve(comp: Component, env: str) -> dict[str, Any]:
    spec = {k: v for k, v in comp.spec.items() if k != "environments"}
    over = (comp.spec.get("environments") or {}).get(env) or {}
    merged = deep_merge(spec, over)
    prod = comp.product
    return _fill(merged, {"env": env, "project": prod.project(env), "product": prod.name})


def seconds(value: Any) -> int:
    return int(str(value).removesuffix("s"))


def duration(value: Any) -> str:
    return f"{seconds(value)}s"


def _probe(p: dict[str, Any] | None) -> dict[str, Any] | None:
    if p is None:
        return None
    out: dict[str, Any] = {"http_path": p.get("http"), "port": p.get("port")}
    for src, dst in [("initial_delay", "initial_delay_seconds"), ("period", "period_seconds"),
                     ("timeout", "timeout_seconds")]:  # fmt: skip
        if src in p:
            out[dst] = seconds(p[src])
    if "failure_threshold" in p:
        out["failure_threshold"] = p["failure_threshold"]
    return {k: v for k, v in out.items() if v is not None}


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != {}}


def compile_component(comp: Component, env: str, errors: list[str]) -> dict[str, Any]:
    c = resolve(comp, env)
    prod = comp.product
    where = f"{comp.product.repo.rel(comp.config_file)} ({env})"
    container = c.get("container") or {}
    resources = c.get("resources") or {}
    scaling = c.get("scaling") or {}
    network = c.get("network") or {}
    perms = dict(c.get("permissions") or {})
    health = c.get("health") or {}

    env_vars: dict[str, str] = {}
    secret_env: dict[str, str] = {}
    for k, v in (c.get("env") or {}).items():
        if isinstance(v, dict):
            secret_env[k] = f"{v['secret']}:{v.get('version', 'latest')}"
        else:
            env_vars[k] = str(v).lower() if isinstance(v, bool) else str(v)
    env_vars = {"ENV": env, "PRODUCT": prod.name, "COMPONENT": comp.name, **env_vars}

    calls = []
    for target in c.get("calls") or []:
        t = prod.components.get(target)
        if t is None or t.kind.type not in ("service", "function"):
            errors.append(f"{where}: calls '{target}', which isn't an app, api or function of {prod.name}")
            continue
        calls.append(f"{t.kind.type}/{target}")

    public = perms.pop("public", False)
    invokers = []
    for i in perms.pop("invokers", []) or []:
        if i in prod.components:
            invokers.append(f"{prod.components[i].kind.type}/{i}")
        elif ":" in i or i in ("allUsers", "allAuthenticatedUsers"):
            invokers.append(i)
        else:
            errors.append(f"{where}: invoker '{i}' is neither a component of {prod.name} nor an IAM member")
    if public:
        invokers.append("allUsers")

    out: dict[str, Any] = {
        "command": container.get("command"),
        "args": container.get("args"),
        "env": env_vars,
        "secret_env": secret_env,
        "cpu": str(resources["cpu"]) if "cpu" in resources else None,
        "memory": resources.get("memory"),
        "egress": EGRESS[network["egress"]] if "egress" in network else None,
        "calls": calls or None,
        "access": _clean(perms) or None,
    }

    typ = comp.kind.type
    if typ in ("service", "function"):
        ingress = network.get("ingress", "all" if public else "internal")
        if public and ingress == "internal":
            errors.append(f"{where}: permissions.public needs network.ingress 'all' or 'load-balancer'")
        out |= {
            "ingress": INGRESS[ingress],
            "min_instances": scaling.get("min_instances"),
            "max_instances": scaling.get("max_instances"),
            "concurrency": scaling.get("concurrency"),
            "timeout": duration(c["timeout"]) if "timeout" in c else None,
            "invokers": invokers or None,
        }
    if typ == "service":
        out |= {
            "port": container.get("port"),
            "cpu_idle": resources.get("cpu_idle"),
            "startup_cpu_boost": resources.get("startup_cpu_boost"),
            "session_affinity": c.get("session_affinity"),
            "startup_probe": _probe(health.get("startup")),
            "liveness_probe": _probe(health.get("liveness")),
        }
    if typ in ("service", "job") and "execution_environment" in c:
        out["execution_environment"] = EXEC_ENV[c["execution_environment"]]
    if typ == "job":
        ex = c.get("execution") or {}
        out |= {
            "task_count": ex.get("tasks"),
            "parallelism": ex.get("parallelism"),
            "max_retries": ex.get("max_retries"),
            "timeout": duration(ex["task_timeout"]) if "task_timeout" in ex else None,
            "schedules": c.get("schedules"),
        }
    if typ == "worker-pool":
        out |= {
            "instances": scaling.get("instances"),
            "startup_probe": _probe(health.get("startup")),
            "liveness_probe": _probe(health.get("liveness")),
        }
    if typ == "function":
        out["triggers"] = c.get("triggers")
    return {k: v for k, v in out.items() if v is not None}


def compile_product(prod: Product, env: str) -> dict[str, Any]:
    platform = prod.repo.platform
    env_cfg = platform["envs"][env]
    errors: list[str] = []
    workloads: dict[str, dict[str, Any]] = {v: {} for v in MODULE_INPUT.values()}
    for comp in prod.components.values():
        workloads[MODULE_INPUT[comp.kind.type]][comp.name] = compile_component(comp, env, errors)
    if errors:
        raise CdkError("deployment.yml problems:\n  - " + "\n  - ".join(errors))
    vpc = env_cfg.get("vpc")
    return {
        "config": {
            "product": prod.name,
            "team": prod.team,
            "env": env,
            "project_id": prod.project(env),
            "region": prod.region,
            "labels": prod.spec.get("labels") or {},
            "vpc": {"network": vpc["network"], "subnetwork": vpc["subnetwork"]} if vpc else None,
            "deployers": list(platform.get("deployers") or []),
            "deletion_protection": env_cfg.get("deletion_protection", True),
            **workloads,
        }
    }
