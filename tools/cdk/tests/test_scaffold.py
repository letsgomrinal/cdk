from pathlib import Path

import pytest
from cdk import scaffold
from cdk.model import CdkError, Repo, load_yaml
from conftest import quiet


def test_new_product_scaffolds_every_kind(orders: Repo) -> None:
    repo = Repo.load(orders.root)
    prod = repo.product("orders")
    assert {c.name: c.workload for c in prod.components.values()} == {
        "storefront": "orders-storefront-svc",
        "backend": "orders-backend-svc",
        "nightly": "orders-nightly-job",
        "mailer": "orders-mailer-wp",
        "ingest": "orders-ingest-fn",
    }
    assert (prod.path / "apps/storefront/package.json").read_text().count('"orders-storefront"') == 1
    assert 'name = "orders-backend"' in (prod.path / "apis/backend/pyproject.toml").read_text()
    assert "__PRODUCT__" not in (prod.path / "jobs/nightly/main.py").read_text()
    assert {c.name: c.kind.section for c in prod.components.values()} == {
        "storefront": "apps",
        "backend": "apis",
        "nightly": "jobs",
        "mailer": "workers",
        "ingest": "functions",
    }
    assert (prod.path / "product.yaml").read_text().startswith("# yaml-language-server: $schema=")


def test_add_and_remove(orders: Repo) -> None:
    root = orders.root
    scaffold.add_component(orders, "orders", "api", "search", None, quiet, run_lock=False)
    assert load_yaml(root / "products/orders/product.yaml")["apis"]["search"]["template"] == "fastapi"
    assert (root / "products/orders/apis/search/main.py").exists()

    notes = scaffold.remove_component(Repo.load(root), "orders", "search", keep_code=False, log=quiet)
    assert "search" not in load_yaml(root / "products/orders/product.yaml")["apis"]
    assert not (root / "products/orders/apis/search").exists()
    assert any("Deletion protection is on in prod" in n for n in notes)


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (("orders", "api", "backend", None), r"already has a component named 'backend' \(in apis\)"),
        (("orders", "job", "backend", None), r"already has a component named 'backend' \(in apis\)"),
        (("orders", "api", "Bad", None), r"must be 1-15 chars"),
        (("orders", "app", "site", "angular"), "isn't available for app"),
        (("nope", "api", "x", None), "no product 'nope'"),
    ],
)
def test_add_rejects(orders: Repo, args: tuple, error: str) -> None:
    with pytest.raises(CdkError, match=error):
        scaffold.add_component(orders, *args, log=quiet, run_lock=False)


def test_new_product_rejects_bad_input(root: Path) -> None:
    repo = Repo.load(root)
    with pytest.raises(CdkError, match="2-10 chars"):
        scaffold.new_product(repo, "orders-api", "t", ["dev"], [], quiet)
    with pytest.raises(CdkError, match=r"isn't in platform\.yaml"):
        scaffold.new_product(repo, "orders", "t", ["staging"], [], quiet)


def test_folder_must_match_product_name(orders: Repo) -> None:
    (orders.root / "products/orders").rename(orders.root / "products/shop")
    with pytest.raises(CdkError, match="must live in products/orders/"):
        Repo.load(orders.root)


def test_same_name_in_two_sections_is_rejected(orders: Repo) -> None:
    path = orders.root / "products/orders/product.yaml"
    path.write_text(path.read_text().replace("jobs:", "jobs:\n  backend: {}", 1))
    with pytest.raises(CdkError, match="'backend' is in both apis and jobs"):
        Repo.load(orders.root)
