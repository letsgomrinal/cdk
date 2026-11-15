import re

import pytest
from cdk.model import KINDS, CdkError
from cdk.schema import all_schemas, validate_deployment

PLATFORM = {"envs": {"dev": {}, "prod": {}}}


def check(kind: str, doc: dict | None) -> None:
    validate_deployment(doc, KINDS[kind], PLATFORM, "x")


def test_valid_documents_pass() -> None:
    check("api", {
        "container": {"port": 8000},
        "resources": {"cpu": 2, "memory": "1Gi", "startup_cpu_boost": True},
        "scaling": {"min_instances": 1, "max_instances": 5, "concurrency": 40},
        "timeout": "60s",
        "network": {"ingress": "internal", "egress": "all-traffic"},
        "health": {"startup": {"http": "/healthz", "period": "5s"}, "liveness": {"port": 8000}},
        "env": {"A": "x", "B": 3, "C": True, "D": {"secret": "s", "version": 2}},
        "permissions": {"public": False, "invokers": ["job1"], "buckets": {"b": "write"}},
        "calls": ["other"],
        "labels": {"tier": "critical", "data-classification": "pii"},
        "environments": {"prod": {"scaling": {"min_instances": 3}}},
    })  # fmt: skip
    check("job", {"execution": {"tasks": 4, "task_timeout": 900}, "schedules": {"d": {"cron": "0 2 * * *"}}})
    check("worker", {"scaling": {"instances": 2}, "health": {"liveness": {"http": "/h", "port": 9000}}})
    check("function", {"triggers": {"t": {"event_type": "x"}}, "permissions": {"public": True}})
    check("job", None)  # an empty deployment.yml is fine


@pytest.mark.parametrize(
    ("kind", "doc", "expected"),
    [
        ("job", {"scaling": {"min_instances": 1}}, "unknown key 'scaling'"),
        ("api", {"schedules": {}}, "unknown key 'schedules'"),
        ("worker", {"network": {"ingress": "all"}}, "network: unknown key 'ingress'"),
        ("job", {"permissions": {"public": True}}, "permissions: unknown key 'public'"),
        ("function", {"container": {"args": ["x"]}}, "unknown key 'container'"),
        ("api", {"resources": {"memroy": "1Gi"}}, "resources: unknown key 'memroy' (allowed: cpu, cpu_idle"),
        ("api", {"resources": {"memory": "1GB"}}, "does not match"),
        ("api", {"network": {"egress": "private"}}, "'private' is not one of"),
        ("api", {"env": {"X": {"secret_id": "s"}}}, "env.X: expected a value or { secret: <id>, version: <n> }"),
        ("api", {"environments": {"staging": {}}}, "'staging' is not one of"),
        ("api", {"environments": {"prod": {"template": "x"}}}, "unknown key 'template'"),
        ("api", {"timeout": "5m"}, "does not match"),
        ("job", {"labels": {"Tier": "x"}}, "'Tier' does not match"),
        ("job", {"labels": {"tier": "Critical"}}, "'Critical' does not match"),
        ("worker", {"labels": {"env": "x"}}, "label 'env' is reserved"),
    ],
)
def test_errors_name_the_problem(kind: str, doc: dict, expected: str) -> None:
    with pytest.raises(CdkError, match=re.escape(expected)):
        check(kind, doc)


def test_one_schema_file_per_kind() -> None:
    assert set(all_schemas(["dev"])) == {f"{k}.schema.json" for k in KINDS}
