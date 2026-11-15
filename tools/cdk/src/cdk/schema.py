"""JSON Schemas for product.yaml and each deployment type's deployment.yml.

Each schema drives:
  - editor autocomplete + inline errors (written to platform/schema/ by `cdk sync`)
  - `cdk` validation, before anything is compiled for Terraform

deployment.yml exposes what that Cloud Run resource type supports; a job's file
can't contain `scaling.min_instances` and an api's can't contain `schedules`.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator

from cdk.model import KINDS, PRODUCT_RE, CdkError, Kind

SCHEMA_DRAFT = "http://json-schema.org/draft-07/schema#"

STR_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
POS_INT: dict[str, Any] = {"type": "integer", "minimum": 0}
DURATION: dict[str, Any] = {
    "type": ["string", "integer"],
    "pattern": r"^[0-9]+s$",
    "description": 'Seconds: "300s" or 300',
}


def obj(description: str, properties: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"type": "object", "description": description, "additionalProperties": False, "properties": properties,
            **extra}  # fmt: skip


PROBE = obj(
    "Health check. With `http` it's an HTTP GET, otherwise a TCP check on the port.",
    {
        "http": {"type": "string", "pattern": "^/", "description": "HTTP path, e.g. /healthz"},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535, "description": "Default: the container port"},
        "initial_delay": DURATION,
        "period": DURATION,
        "timeout": DURATION,
        "failure_threshold": {"type": "integer", "minimum": 1},
    },
)

ENV = {
    "type": "object",
    "description": "Env vars: a value, or a Secret Manager secret. ENV, PRODUCT, COMPONENT are always set.",
    "propertyNames": {"pattern": r"^[A-Za-z_][A-Za-z0-9_]*$"},
    "additionalProperties": {
        "oneOf": [
            {"type": ["string", "number", "boolean"]},
            obj(
                "Secret reference. Access to the secret is granted automatically.",
                {
                    "secret": {"type": "string", "description": 'Secret ID, or "projects/p/secrets/x"'},
                    "version": {"type": ["string", "integer"], "description": "Default: latest"},
                },
                required=["secret"],
            ),
        ]
    },
}

PERMISSIONS: dict[str, Any] = {
    "secrets": {**STR_LIST, "description": "secretAccessor on each secret (env secrets are granted already)"},
    "buckets": {
        "type": "object",
        "additionalProperties": {"enum": ["read", "write", "admin"]},
        "description": "bucket: read | write | admin",
    },
    "publish": {**STR_LIST, "description": "pubsub.publisher on each topic"},
    "subscribe": {**STR_LIST, "description": "pubsub.subscriber on each subscription"},
    "bigquery_datasets": {
        "type": "object",
        "additionalProperties": {"enum": ["read", "write"]},
        "description": '"dataset" or "project:dataset": read | write',
    },
    "project_roles": {**STR_LIST, "description": "Escape hatch: project-wide roles (reviewed)"},
}
HTTP_PERMISSIONS: dict[str, Any] = {
    "public": {"type": "boolean", "description": "Anyone on the internet may call it (allUsers invoker)"},
    "invokers": {**STR_LIST, "description": "Who may call it: component names or IAM members"},
}

INGRESS = {"enum": ["internal", "load-balancer", "all"], "description": "Who can reach it on the network"}
EGRESS = {
    "enum": ["private-ranges", "all-traffic", "none"],
    "description": "Outbound via the env's VPC: private IPs only (default), all traffic, or no VPC",
}
CPU = {"type": ["string", "number"], "description": 'vCPUs: "1", "2", "4", "8" (services also "0.5")'}
MEMORY = {"type": "string", "pattern": r"^[0-9]+(Mi|Gi)$", "description": "e.g. 512Mi, 2Gi"}
EXEC_ENV = {"enum": ["gen1", "gen2"], "description": "Cloud Run execution environment (default: Cloud Run decides)"}


def _blocks(kind: Kind) -> dict[str, Any]:
    """Top-level keys of deployment.yml for one kind."""
    http = kind.type in ("service", "function")
    container: dict[str, Any] = {"command": STR_LIST, "args": STR_LIST}
    if kind.type == "service":
        container["port"] = {"type": "integer", "minimum": 1, "maximum": 65535, "description": "Default 8080"}
    resources: dict[str, Any] = {"cpu": CPU, "memory": MEMORY}
    if kind.type == "service":
        resources["cpu_idle"] = {"type": "boolean", "description": "CPU only while handling requests (default true)"}
        resources["startup_cpu_boost"] = {"type": "boolean", "description": "Extra CPU during startup"}

    blocks: dict[str, Any] = {
        "template": {"type": "string", "description": "Scaffold this was created from (informational)"},
    }
    if kind.type != "function":  # functions run the Functions Framework entrypoint
        blocks["container"] = obj("How the container runs", container)
    blocks["resources"] = obj("CPU and memory per instance", resources)

    if kind.type in ("service", "function"):
        blocks["scaling"] = obj(
            "Autoscaling",
            {
                "min_instances": {**POS_INT, "description": "Default 0 (scale to zero)"},
                "max_instances": {"type": "integer", "minimum": 1, "description": "Default 10"},
                "concurrency": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Requests per instance (default 80; functions 1)",
                },
            },
        )
        blocks["timeout"] = {**DURATION, "description": "Request timeout (default 300s)"}
    if kind.type == "worker-pool":
        blocks["scaling"] = obj("Instances", {"instances": {**POS_INT, "description": "Always-on instances"}})
    if kind.type == "job":
        blocks["execution"] = obj(
            "How each execution runs",
            {
                "tasks": {"type": "integer", "minimum": 1, "description": "Tasks per execution (default 1)"},
                "parallelism": {**POS_INT, "description": "Tasks at once (default 0 = all)"},
                "max_retries": {**POS_INT, "description": "Retries per failed task (default 3)"},
                "task_timeout": {**DURATION, "description": "Per task (default 600s)"},
            },
        )
        blocks["schedules"] = {
            "type": "object",
            "description": "Cloud Scheduler triggers",
            "additionalProperties": obj(
                "One schedule",
                {
                    "cron": {"type": "string", "description": 'e.g. "0 2 * * *"'},
                    "time_zone": {"type": "string", "description": "IANA name, default Etc/UTC"},
                    "args": {**STR_LIST, "description": "Override container args for this schedule"},
                    "paused": {"type": "boolean"},
                },
                required=["cron"],
            ),
        }
    if kind.type == "service":
        blocks["session_affinity"] = {"type": "boolean", "description": "Route a client to the same instance"}
    if kind.type in ("service", "job"):
        blocks["execution_environment"] = EXEC_ENV
    network: dict[str, Any] = {"egress": EGRESS}
    if http:
        network = {"ingress": INGRESS, **network}
    blocks["network"] = obj("Networking", network)
    if kind.type in ("service", "worker-pool"):
        blocks["health"] = obj("Health checks", {"startup": PROBE, "liveness": PROBE})
    blocks["env"] = ENV
    blocks["permissions"] = obj(
        "IAM for this component's service account, granted on each resource",
        {**(HTTP_PERMISSIONS if http else {}), **PERMISSIONS},
    )
    blocks["calls"] = {
        **STR_LIST,
        "description": "Apps/apis/functions this calls: grants run.invoker and injects <NAME>_URL",
    }
    if kind.type == "function":
        blocks["triggers"] = {
            "type": "object",
            "description": "Eventarc triggers",
            "additionalProperties": obj(
                "One trigger",
                {
                    "event_type": {"type": "string", "description": "e.g. google.cloud.storage.object.v1.finalized"},
                    "filters": {"type": "object", "additionalProperties": {"type": "string"}},
                    "pubsub_topic": {"type": "string"},
                    "path": {"type": "string"},
                },
                required=["event_type"],
            ),
        }
    return blocks


def deployment_schema(kind: Kind, envs: list[str]) -> dict[str, Any]:
    blocks = _blocks(kind)
    overridable = {k: v for k, v in blocks.items() if k != "template"}
    return {
        "$schema": SCHEMA_DRAFT,
        "$id": f"{kind.name}.schema.json",
        "title": f"deployment.yml ({kind.name})",
        "description": f"A {kind.name}: {kind.description}. Runs as a Cloud Run {kind.type}. "
        "Reference: docs/DEPLOYMENT_YML.md",
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            **blocks,
            "environments": {
                "type": "object",
                "description": "Per-env settings, deep-merged over the above (lists are replaced)",
                "propertyNames": {"enum": envs} if envs else {"type": "string"},
                "additionalProperties": {"type": "object", "additionalProperties": False, "properties": overridable},
            },
        },
    }


def product_schema(envs: list[str]) -> dict[str, Any]:
    env_enum = {"enum": envs} if envs else {"type": "string"}
    return {
        "$schema": SCHEMA_DRAFT,
        "$id": "product.schema.json",
        "title": "product.yaml",
        "description": "Product-level settings. Components are the <section>/<name>/deployment.yml folders "
        "next to this file. Reference: docs/DEPLOYMENT_YML.md",
        "type": "object",
        "required": ["product", "team", "envs"],
        "additionalProperties": False,
        "properties": {
            "product": {
                "type": "string",
                "pattern": PRODUCT_RE.pattern,
                "description": "2-10 chars, [a-z][a-z0-9]*. Prefix of every resource and SA name.",
            },
            "team": {"type": "string", "description": "Owning team: GitHub team slug (CODEOWNERS) and label"},
            "envs": {"type": "array", "items": env_enum, "uniqueItems": True, "minItems": 1},
            "region": {"type": "string", "description": "Default: platform.yaml region"},
            "projects": {
                "type": "object",
                "propertyNames": env_enum,
                "additionalProperties": {"type": "string"},
                "description": "Per-env project ID if not {org}-{product}-{env}",
            },
            "labels": {"type": "object", "additionalProperties": {"type": "string"}},
        },
    }


def all_schemas(envs: list[str]) -> dict[str, dict[str, Any]]:
    """file name -> schema, for platform/schema/."""
    out = {"product.schema.json": product_schema(envs)}
    out.update({f"{k.name}.schema.json": deployment_schema(k, envs) for k in KINDS.values()})
    return out


def validate(doc: Any, schema: dict[str, Any], where: str) -> None:
    errors: list[str] = []
    for e in sorted(Draft7Validator(schema).iter_errors(doc), key=lambda e: list(map(str, e.absolute_path))):
        path = ".".join(str(p) for p in e.absolute_path) or "(top level)"
        msg = e.message
        if e.validator == "additionalProperties" and isinstance(e.instance, dict):
            allowed = set(e.schema.get("properties", {}))
            unknown = [k for k in e.instance if k not in allowed]
            msg = "unknown key" + ("s " if len(unknown) > 1 else " ") + ", ".join(repr(k) for k in unknown)
            if allowed:
                msg += f" (allowed: {', '.join(sorted(allowed))})"
        elif e.validator == "oneOf" and isinstance(e.instance, dict):
            msg = "expected a value or { secret: <id>, version: <n> }"
        errors.append(f"{path}: {msg}")
    if errors:
        raise CdkError(f"{where}:\n  - " + "\n  - ".join(dict.fromkeys(errors)))


def validate_product(spec: Any, platform: dict[str, Any], where: str) -> None:
    validate(spec, product_schema(list(platform.get("envs") or {})), where)


def validate_deployment(doc: Any, kind: Kind, platform: dict[str, Any], where: str) -> None:
    validate(doc, deployment_schema(kind, list(platform.get("envs") or {})), where)
