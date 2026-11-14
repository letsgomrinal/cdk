import re

import pytest
from cdk.model import KINDS, CdkError
from cdk.schema import TYPE_KEYS, validate_product
from conftest import REAL_ROOT

PLATFORM = {"envs": {"dev": {}, "prod": {}}}


def spec(**components: dict) -> dict:
    return {"product": "orders", "team": "t", "envs": ["dev"], "components": components}


def test_valid_spec_passes() -> None:
    validate_product(
        spec(
            api={"kind": "api", "memory": "1Gi", "access": {"buckets": {"b": "write"}}, "calls": ["web"]},
            web={"kind": "web", "public": True},
            job={"kind": "job", "schedules": {"d": {"cron": "0 2 * * *", "args": ["x"]}}},
        ),
        PLATFORM,
        "x",
    )


@pytest.mark.parametrize(
    ("component", "expected"),
    [
        ({"kind": "api", "memroy": "1Gi"}, "unknown key 'memroy' for kind api"),
        ({"kind": "job", "public": True}, "unknown key 'public' for kind job"),
        ({"kind": "lambda"}, "'lambda' is not one of"),
        ({"kind": "api", "memory": "1GB"}, "does not match"),
        ({"kind": "job", "access": {"buckets": {"b": "owner"}}}, "'owner' is not one of"),
    ],
)
def test_errors_name_the_problem(component: dict, expected: str) -> None:
    with pytest.raises(CdkError, match=re.escape(expected)):
        validate_product(spec(c=component), PLATFORM, "x")


def test_unknown_env_and_bad_names() -> None:
    bad = {"product": "Orders-1", "team": "t", "envs": ["stage"], "components": {"Bad_Name": {"kind": "api"}}}
    with pytest.raises(CdkError) as e:
        validate_product(bad, PLATFORM, "x")
    msg = str(e.value)
    assert "product: 'Orders-1' does not match" in msg
    assert "'stage' is not one of" in msg
    assert "'Bad_Name' does not match" in msg


def _hcl_list(text: str, name: str) -> list[str]:
    m = re.search(rf"{re.escape(name)}\s*=\s*(.+)", text)
    assert m, name
    return re.findall(r'"([a-z_]+)"', m.group(1))


def test_schema_matches_terraform_allowed_keys() -> None:
    """platform/terraform/modules/product-spec must accept exactly what the schema allows."""
    tf = (REAL_ROOT / "platform/terraform/modules/product-spec/main.tf").read_text()
    common = _hcl_list(tf, "common_keys")
    block = re.search(r"allowed_keys = \{(.*?)\n  \}", tf, re.S)
    assert block
    for typ, keys in TYPE_KEYS.items():
        line = next(ln for ln in block.group(1).splitlines() if ln.strip().startswith((f"{typ} ", f'"{typ}"')))
        tf_keys = set(common) | set(_hcl_list(line, line.split("=")[0].strip()))
        assert tf_keys == set(keys), f"{typ}: terraform={sorted(tf_keys)} schema={sorted(keys)}"
    tf_kinds = re.search(r"kinds = \{(.*?)\}", tf, re.S)
    assert tf_kinds
    assert set(re.findall(r"(\w+)\s*=", tf_kinds.group(1))) == set(KINDS)
