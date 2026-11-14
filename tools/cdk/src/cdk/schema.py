"""JSON Schema for product.yaml.

One schema drives three things:
  - editor autocomplete + inline errors (written to platform/schema/product.schema.json)
  - `cdk` validation (fast feedback before Terraform)
  - a test that keeps it in step with the keys modules/product-spec accepts
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator

from cdk.model import COMPONENT_RE, KINDS, PRODUCT_RE, CdkError

STR_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
POS_INT: dict[str, Any] = {"type": "integer", "minimum": 0}
DURATION: dict[str, Any] = {"type": "string", "pattern": r"^[0-9]+s$", "description": "Seconds, e.g. 300s"}

# Every setting a component can have. Which kinds allow which key is in KIND_KEYS.
PROPERTIES: dict[str, dict[str, Any]] = {
    "kind": {
        "enum": list(KINDS),
        "description": "web | api -> Cloud Run service; job; worker -> worker pool; function",
    },
    "template": {
        "enum": sorted({t for k in KINDS.values() for t in k.templates}),
        "description": "Scaffold used by `cdk add` (informational)",
    },
    "env": {
        "type": "object",
        "additionalProperties": {"type": ["string", "number", "boolean"]},
        "description": "Plain env vars. ENV, PRODUCT, COMPONENT are always set.",
    },
    "secret_env": {
        "type": "object",
        "additionalProperties": {"type": "string"},
        "description": 'ENV_VAR: "secret-id" or "secret-id:version". Accessor is granted automatically.',
    },
    "cpu": {"type": ["string", "number"], "description": 'vCPUs, e.g. "1", "2"'},
    "memory": {"type": "string", "pattern": r"^[0-9]+(Mi|Gi)$", "description": "e.g. 512Mi, 1Gi"},
    "use_vpc": {"type": "boolean", "description": "Attach the env's VPC egress (default true)"},
    "calls": {**STR_LIST, "description": "Components this one calls: grants run.invoker and injects <NAME>_URL"},
    "access": {
        "type": "object",
        "additionalProperties": False,
        "description": "Resource-level IAM for this component's service account",
        "properties": {
            "secrets": {**STR_LIST, "description": "secretAccessor on each secret"},
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
        },
    },
    "image": {"type": "string", "description": "Initial image only; releases set the image afterwards"},
    "command": STR_LIST,
    "args": STR_LIST,
    "public": {"type": "boolean", "description": "Internet-facing: ingress ALL + allUsers invoker"},
    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
    "ingress": {
        "enum": ["INGRESS_TRAFFIC_ALL", "INGRESS_TRAFFIC_INTERNAL_ONLY", "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"]
    },
    "min_instances": POS_INT,
    "max_instances": {"type": "integer", "minimum": 1},
    "concurrency": {"type": "integer", "minimum": 1},
    "timeout": DURATION,
    "cpu_idle": {"type": "boolean", "description": "CPU only during requests (default true)"},
    "invokers": {**STR_LIST, "description": "Who may call this: component names or IAM members"},
    "task_count": {"type": "integer", "minimum": 1},
    "parallelism": POS_INT,
    "max_retries": POS_INT,
    "schedules": {
        "type": "object",
        "description": "Cloud Scheduler triggers for this job",
        "additionalProperties": {
            "type": "object",
            "required": ["cron"],
            "additionalProperties": False,
            "properties": {
                "cron": {"type": "string", "description": 'e.g. "0 2 * * *"'},
                "time_zone": {"type": "string", "description": "IANA name, default Etc/UTC"},
                "args": {**STR_LIST, "description": "Override container args for this schedule"},
                "paused": {"type": "boolean"},
            },
        },
    },
    "instances": {**POS_INT, "description": "Worker pool instance count"},
    "triggers": {
        "type": "object",
        "description": "Eventarc triggers delivering events to this function",
        "additionalProperties": {
            "type": "object",
            "required": ["event_type"],
            "additionalProperties": False,
            "properties": {
                "event_type": {"type": "string", "description": "e.g. google.cloud.storage.object.v1.finalized"},
                "filters": {"type": "object", "additionalProperties": {"type": "string"}},
                "pubsub_topic": {"type": "string"},
                "path": {"type": "string"},
            },
        },
    },
}

COMMON = ["kind", "template", "env", "secret_env", "cpu", "memory", "use_vpc", "access", "calls"]
CONTAINER = ["image", "command", "args"]
HTTP = ["public", "ingress", "min_instances", "max_instances", "concurrency", "timeout", "invokers"]

# Keys allowed per Cloud Run type. Must match allowed_keys in modules/product-spec (tested).
TYPE_KEYS: dict[str, list[str]] = {
    "service": [*COMMON, *CONTAINER, *HTTP, "port", "cpu_idle"],
    "job": [*COMMON, *CONTAINER, "task_count", "parallelism", "max_retries", "timeout", "schedules"],
    "worker-pool": [*COMMON, *CONTAINER, "instances"],
    "function": [*COMMON, *HTTP, "triggers"],
}


def kind_keys(kind: str) -> list[str]:
    return TYPE_KEYS[KINDS[kind].type]


def build_schema(envs: list[str]) -> dict[str, Any]:
    env_enum = {"enum": envs} if envs else {"type": "string"}
    component: dict[str, Any] = {
        "type": "object",
        "required": ["kind"],
        "properties": PROPERTIES,  # union, for autocomplete
        "allOf": [
            {
                "if": {"properties": {"kind": {"const": k}}, "required": ["kind"]},
                "then": {"propertyNames": {"enum": kind_keys(k)}},
            }
            for k in KINDS
        ],
    }
    override = {
        "type": "object",
        "propertyNames": {"not": {"const": "kind"}},
        "properties": {k: v for k, v in PROPERTIES.items() if k != "kind"},
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "product.schema.json",
        "title": "product.yaml",
        "description": "A product in this monorepo. Reference: docs/PRODUCT_YAML.md",
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
            "region": {"type": "string"},
            "projects": {
                "type": "object",
                "propertyNames": env_enum,
                "additionalProperties": {"type": "string"},
                "description": "Per-env project ID if not {org}-{product}-{env}",
            },
            "labels": {"type": "object", "additionalProperties": {"type": "string"}},
            "components": {
                "type": "object",
                "propertyNames": {"pattern": COMPONENT_RE.pattern},
                "additionalProperties": component,
            },
            "overrides": {
                "type": "object",
                "propertyNames": env_enum,
                "additionalProperties": {"type": "object", "additionalProperties": override},
                "description": "Per-env, per-component settings, shallow-merged",
            },
        },
    }


def _at(doc: Any, path: list[Any]) -> Any:
    for p in path:
        doc = doc[p]
    return doc


def validate_product(spec: Any, platform: dict[str, Any], where: str) -> None:
    schema = build_schema(list(platform.get("envs") or {}))
    errors: list[str] = []
    for e in sorted(Draft7Validator(schema).iter_errors(spec), key=lambda e: list(map(str, e.absolute_path))):
        path = ".".join(str(p) for p in e.absolute_path) or "(top level)"
        msg = e.message
        if e.validator == "enum" and "propertyNames" in e.schema_path:
            msg = f"unknown key {e.instance!r}"
            parent = _at(spec, list(e.absolute_path))
            if isinstance(parent, dict) and parent.get("kind"):
                msg += f" for kind {parent['kind']} (see docs/PRODUCT_YAML.md)"
        errors.append(f"{path}: {msg}")
    if errors:
        raise CdkError(f"{where}:\n  - " + "\n  - ".join(dict.fromkeys(errors)))
