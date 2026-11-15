import pytest
from cdk.affected import affected, changed_files, resolve_base
from cdk.model import Repo
from conftest import git


def _commit(repo: Repo, path: str, text: str = "x\n") -> str:
    f = repo.root / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", f"change {path}")
    return git(repo.root, "rev-parse", "HEAD").strip()


def keys(repo: Repo, files: list[str] | None, scope: str) -> list[str]:
    return sorted(c.key for c in affected(repo, files, scope))  # type: ignore[arg-type]


def test_component_change(orders: Repo) -> None:
    base = git(orders.root, "rev-parse", "HEAD").strip()
    _commit(orders, "products/orders/apis/backend/main.py")
    files = changed_files(orders, base)
    assert files == ["products/orders/apis/backend/main.py"]
    assert keys(orders, files, "release") == ["orders/backend"]
    assert keys(orders, files, "check") == ["orders/backend"]


def test_deployment_yml_alone_is_not_a_release(orders: Repo) -> None:
    files = ["products/orders/apis/backend/deployment.yml"]
    assert keys(orders, files, "release") == []
    assert keys(orders, files, "check") == ["orders/backend"]


def test_shared_config_affects_all_checks_but_no_release(orders: Repo) -> None:
    files = ["pyproject.toml", "README.md"]
    assert len(keys(orders, files, "check")) == 5
    assert keys(orders, files, "release") == []
    assert keys(orders, ["README.md"], "check") == []


def test_prefix_is_not_a_false_match(orders: Repo) -> None:
    assert keys(orders, ["products/orders/apis/backend-old/x.py"], "release") == []


def test_uncommitted_changes_count(orders: Repo) -> None:
    base = git(orders.root, "rev-parse", "HEAD").strip()
    (orders.root / "products/orders/jobs/nightly/new.py").write_text("x = 1\n")
    assert changed_files(orders, base) == ["products/orders/jobs/nightly/new.py"]


@pytest.mark.parametrize("base", [None, "0000000000000000000000000000000000000000", "deadbeef"])
def test_unknown_base_means_everything(orders: Repo, base: str | None) -> None:
    assert changed_files(orders, base) is None
    assert len(keys(orders, None, "release")) == 5


def test_base_resolution(orders: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_base(orders, "abc") == "abc"
    monkeypatch.setenv("DRONE_COMMIT_BEFORE", "def")
    assert resolve_base(orders) == "def"
    monkeypatch.setenv("CDK_BASE", "ghi")
    assert resolve_base(orders) == "ghi"
