from cdk import generate
from cdk.model import Repo


def test_sync_is_idempotent_and_check_detects_drift(orders: Repo) -> None:
    assert generate.sync(Repo.load(orders.root), check=True) == []
    (orders.root / "atlantis.yaml").write_text("tampered\n")
    assert generate.sync(Repo.load(orders.root), check=True) == ["atlantis.yaml"]
    generate.sync(Repo.load(orders.root))
    assert generate.sync(Repo.load(orders.root), check=True) == []


def test_generated_files(orders: Repo) -> None:
    root = orders.root
    main_tf = (root / "products/orders/deploy/main.tf").read_text()
    assert 'source = "../../../platform/terraform/modules/product"' in main_tf
    import json

    cfg = json.loads((root / "products/orders/deploy/prod.tfvars.json").read_text())["config"]
    assert cfg["env"] == "prod" and "backend" in cfg["services"]
    plan = (root / "products/orders/deploy/tests/plan.tftest.hcl").read_text()
    assert 'run "plan_prod"' in plan and "length(output.workloads) == 5" in plan
    assert (
        (root / "products/orders/deploy/backend.prod.hcl")
        .read_text()
        .endswith('bucket = "acme-tfstate-prod"\nprefix = "products/orders"\n')
    )
    atlantis = (root / "atlantis.yaml").read_text()
    assert "  - name: orders-dev\n    dir: products/orders/deploy\n    workspace: dev\n" in atlantis
    owners = (root / "CODEOWNERS").read_text()
    assert "*                  @acme/platform\n/products/orders/  @acme/commerce\n" in owners
    assert (root / "platform/schema/product.schema.json").exists()
    assert (root / "platform/schema/worker.schema.json").exists()


def test_removed_env_deletes_backend_file(orders: Repo) -> None:
    path = orders.root / "products/orders/product.yaml"
    path.write_text(path.read_text().replace("envs: [dev, prod]", "envs: [dev]"))
    for f in (orders.root / "products/orders").glob("*/*/deployment.yml"):  # drop prod overrides
        f.write_text(f.read_text().split("environments:")[0])
    changed = generate.sync(Repo.load(orders.root))
    assert "products/orders/deploy/backend.prod.hcl (delete)" in changed
    assert "products/orders/deploy/prod.tfvars.json (delete)" in changed
    assert not (orders.root / "products/orders/deploy/backend.prod.hcl").exists()
    assert "orders-prod" not in (orders.root / "atlantis.yaml").read_text()
