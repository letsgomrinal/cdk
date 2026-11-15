from pathlib import Path

import pytest
from cdk.compile import compile_component, compile_product, deep_merge, resolve
from cdk.model import CdkError, Repo


def write(repo: Repo, rel: str, text: str) -> Repo:
    (repo.root / "products/orders" / rel).write_text(text)
    return Repo.load(repo.root)


def test_deep_merge_replaces_lists_and_merges_dicts() -> None:
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 1}
    assert deep_merge(base, {"a": {"y": [3]}, "c": 2}) == {"a": {"x": 1, "y": [3]}, "b": 1, "c": 2}
    assert base == {"a": {"x": 1, "y": [1, 2]}, "b": 1}  # not mutated


def test_environment_overrides_and_placeholders(orders: Repo) -> None:
    repo = write(
        orders,
        "apis/backend/deployment.yml",
        """
resources: { cpu: "1", memory: 512Mi }
scaling: { min_instances: 0, max_instances: 10 }
permissions: { buckets: { "acme-{product}-{env}": read } }
environments:
  prod:
    scaling: { min_instances: 2 }
""",
    )
    backend = repo.product("orders").components["backend"]
    prod = resolve(backend, "prod")
    assert prod["scaling"] == {"min_instances": 2, "max_instances": 10}
    assert prod["permissions"]["buckets"] == {"acme-orders-prod": "read"}
    assert "environments" not in prod
    assert resolve(backend, "dev")["scaling"]["min_instances"] == 0


def test_compiles_to_module_inputs(orders: Repo) -> None:
    repo = write(
        orders,
        "apis/backend/deployment.yml",
        """
container: { port: 8000 }
resources: { cpu: 2, memory: 1Gi, startup_cpu_boost: true }
timeout: 60
execution_environment: gen2
network: { ingress: load-balancer, egress: none }
health: { startup: { http: /healthz, period: 5s } }
env: { LOG_LEVEL: info, DEBUG: false, DB: { secret: db-url, version: 3 } }
permissions: { invokers: [nightly, "group:ops@acme.com"], publish: [events] }
""",
    )
    out = compile_component(repo.product("orders").components["backend"], "dev", [])
    assert out == {
        "cpu": "2",
        "memory": "1Gi",
        "port": 8000,
        "startup_cpu_boost": True,
        "timeout": "60s",
        "execution_environment": "EXECUTION_ENVIRONMENT_GEN2",
        "ingress": "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER",
        "egress": "NONE",
        "startup_probe": {"http_path": "/healthz", "period_seconds": 5},
        "env": {"ENV": "dev", "PRODUCT": "orders", "COMPONENT": "backend", "LOG_LEVEL": "info", "DEBUG": "false"},
        "secret_env": {"DB": "db-url:3"},
        "invokers": ["job/nightly", "group:ops@acme.com"],
        "access": {"publish": ["events"]},
    }


def test_public_app_defaults_to_ingress_all(orders: Repo) -> None:
    repo = write(orders, "apps/storefront/deployment.yml", "permissions: { public: true }\ncalls: [backend]\n")
    out = compile_component(repo.product("orders").components["storefront"], "dev", [])
    assert out["ingress"] == "INGRESS_TRAFFIC_ALL"
    assert out["invokers"] == ["allUsers"]
    assert out["calls"] == ["service/backend"]


def test_job_and_worker_fields(orders: Repo) -> None:
    repo = write(
        orders,
        "jobs/nightly/deployment.yml",
        """
execution: { tasks: 4, parallelism: 2, max_retries: 1, task_timeout: 900s }
schedules: { d: { cron: "0 2 * * *" } }
""",
    )
    repo = write(
        repo, "workers/mailer/deployment.yml", "scaling: { instances: 3 }\nhealth: { liveness: { port: 9000 } }\n"
    )
    prod = repo.product("orders")
    job = compile_component(prod.components["nightly"], "dev", [])
    assert {k: job[k] for k in ("task_count", "parallelism", "max_retries", "timeout")} == {
        "task_count": 4, "parallelism": 2, "max_retries": 1, "timeout": "900s"
    }  # fmt: skip
    assert job["schedules"] == {"d": {"cron": "0 2 * * *"}}
    worker = compile_component(prod.components["mailer"], "dev", [])
    assert worker["instances"] == 3
    assert worker["liveness_probe"] == {"port": 9000}


def test_semantic_errors_are_collected(orders: Repo) -> None:
    repo = write(
        orders,
        "apps/storefront/deployment.yml",
        """
permissions: { public: true, invokers: [nobody] }
network: { ingress: internal }
calls: [nightly, ghost]
""",
    )
    with pytest.raises(CdkError) as e:
        compile_product(repo.product("orders"), "dev")
    msg = str(e.value)
    assert "calls 'nightly', which isn't an app, api or function" in msg
    assert "calls 'ghost'" in msg
    assert "invoker 'nobody' is neither a component" in msg
    assert "public needs network.ingress 'all' or 'load-balancer'" in msg


def test_product_config(orders: Repo) -> None:
    cfg = compile_product(orders.product("orders"), "prod")["config"]
    assert cfg["project_id"] == "acme-orders-prod"
    assert cfg["deletion_protection"] is True
    assert set(cfg["services"]) == {"storefront", "backend"}
    assert set(cfg["jobs"]) == {"nightly"} and set(cfg["worker_pools"]) == {"mailer"}
    assert set(cfg["functions"]) == {"ingest"}
    assert cfg["vpc"]["network"].endswith("/networks/shared")


def test_templates_are_valid_for_their_kind(root: Path) -> None:
    """Every template's deployment.yml validates and compiles once scaffolded."""
    from cdk import scaffold
    from conftest import quiet

    repo = Repo.load(root)
    pairs = [("app", "nextjs"), ("app", "react"), ("api", "fastapi"), ("job", "python-job"),
             ("worker", "python-worker"), ("function", "python-function")]  # fmt: skip
    adds: list[tuple[str, str, str | None]] = [(k, f"c{i}", t) for i, (k, t) in enumerate(pairs)]
    scaffold.new_product(repo, "shop", "t", ["dev", "prod"], adds, quiet, run_lock=False)
    repo = Repo.load(root)
    for env in ("dev", "prod"):
        compile_product(repo.product("shop"), env)
