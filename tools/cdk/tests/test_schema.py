import re

import pytest
from cdk.model import KINDS, CdkError
from cdk.schema import TYPE_KEYS, validate_product
from conftest import REAL_ROOT

PLATFORM = {"envs": {"dev": {}, "prod": {}}}


def spec(**sections: dict | None) -> dict:
    return {"product": "orders", "team": "t", "envs": ["dev"], **sections}


def test_valid_spec_passes() -> None:
    validate_product(
        spec(
            apps={"web": {"public": True, "calls": ["api"]}},
            apis={"api": {"memory": "1Gi", "access": {"buckets": {"b": "write"}}}},
            jobs={"job": {"schedules": {"d": {"cron": "0 2 * * *", "args": ["x"]}}}, "bare": None},
            workers=None,
            overrides={"prod": {"apis": {"api": {"min_instances": 2}}}},
        ),
        PLATFORM,
        "x",
    )


@pytest.mark.parametrize(
    ("sections", "expected"),
    [
        ({"apis": {"c": {"memroy": "1Gi"}}}, "apis.c: unknown key 'memroy' for apis"),
        ({"jobs": {"c": {"public": True}}}, "jobs.c: unknown key 'public' for jobs"),
        ({"apis": {"c": {"kind": "api"}}}, "unknown key 'kind'"),
        ({"lambdas": {"c": {}}}, "(top level): unknown key 'lambdas'"),
        ({"apis": {"c": {"memory": "1GB"}}}, "does not match"),
        ({"jobs": {"c": {"access": {"buckets": {"b": "owner"}}}}}, "'owner' is not one of"),
        ({"overrides": {"prod": {"jobs": {"c": {"template": "x"}}}}}, "unknown key 'template'"),
    ],
)
def test_errors_name_the_problem(sections: dict, expected: str) -> None:
    with pytest.raises(CdkError, match=re.escape(expected)):
        validate_product(spec(**sections), PLATFORM, "x")


def test_unknown_env_and_bad_names() -> None:
    bad = {"product": "Orders-1", "team": "t", "envs": ["stage"], "apis": {"Bad_Name": {}}}
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


def test_schema_matches_terraform_module() -> None:
    """platform/terraform/modules/product-spec must accept exactly what the schema allows."""
    tf = (REAL_ROOT / "platform/terraform/modules/product-spec/main.tf").read_text()
    common = _hcl_list(tf, "common_keys")
    block = re.search(r"allowed_keys = \{(.*?)\n  \}", tf, re.S)
    assert block
    for typ, keys in TYPE_KEYS.items():
        line = next(ln for ln in block.group(1).splitlines() if ln.strip().startswith((f"{typ} ", f'"{typ}"')))
        tf_keys = set(common) | set(_hcl_list(line, line.split("=")[0].strip()))
        assert tf_keys == set(keys), f"{typ}: terraform={sorted(tf_keys)} schema={sorted(keys)}"
    sections = re.search(r"sections = \{(.*?)\}", tf, re.S)
    assert sections
    tf_sections = dict(re.findall(r'(\w+)\s*=\s*"([\w-]+)"', sections.group(1)))
    assert tf_sections == {k.section: k.type for k in KINDS.values()}
