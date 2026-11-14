import pytest
from cdk.model import Repo
from cdk.release import first_container_image, promote, release
from conftest import git, quiet


def test_release_builds_and_deploys_changed_components_only(orders: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    base = git(orders.root, "rev-parse", "HEAD").strip()
    (orders.root / "products/orders/mailer/main.py").write_text("print('v2')\n")
    git(orders.root, "commit", "-qam", "v2")
    monkeypatch.setenv("DRONE_COMMIT_SHA", "a" * 40)

    run = release(Repo.load(orders.root), "dev", quiet, since=base, dry_run=True)
    image = "europe-west1-docker.pkg.dev/acme-artifacts/products/orders/mailer:aaaaaaaaaaaa"
    assert run.commands == [
        ["gcloud", "builds", "submit", "products/orders/mailer", "--tag", image, "--project", "acme-cicd", "--quiet"],
        ["gcloud", "beta", "run", "worker-pools", "deploy", "orders-mailer-wp", "--image", image,
         "--project", "acme-orders-dev", "--region", "europe-west1", "--quiet"],
    ]  # fmt: skip


def test_release_explicit_components(orders: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPONENTS", "orders/nightly,ingest")
    run = release(orders, "prod", quiet, build=False, dry_run=True)
    assert [c[:5] for c in run.commands] == [
        ["gcloud", "run", "jobs", "update", "orders-nightly-job"],
        ["gcloud", "run", "services", "update", "orders-ingest-fn"],
    ]


def test_promote_describes_source_then_deploys(orders: Repo) -> None:
    run = promote(orders, "dev", "prod", quiet, components="orders/backend", dry_run=True)
    assert run.commands[0][:5] == ["gcloud", "run", "services", "describe", "orders-backend-svc"]
    assert "acme-orders-dev" in run.commands[0]
    assert run.commands[1][:4] == ["gcloud", "run", "services", "update"]
    assert "acme-orders-prod" in run.commands[1]


@pytest.mark.parametrize(
    "doc",
    [
        {"spec": {"template": {"spec": {"containers": [{"image": "img:1"}]}}}},  # service (v1 shape)
        {"spec": {"template": {"spec": {"template": {"spec": {"containers": [{"image": "img:1"}]}}}}}},  # job
        {"template": {"containers": [{"image": "img:1"}, {"image": "sidecar"}]}},  # v2 shape
    ],
)
def test_first_container_image(doc: dict) -> None:
    assert first_container_image(doc) == "img:1"
