from cdk.scaffold import PRODUCT_HEADER, SNIPPETS
from cdk.yamledit import delete_component, insert_component

DOC = """\
# header comment
product: orders
team: commerce

apis:  # backends
  api:
    template: fastapi
    # a comment inside api

  search:
    template: fastapi

jobs: {}  # batch

# overrides comment belongs to the next section
overrides:
  prod:
    apis:
      api: { min_instances: 2 }
"""


def test_insert_appends_to_section_keeping_comments() -> None:
    out = insert_component(DOC, "apis", "web", "port: 3000  # note\n")
    assert "  search:\n    template: fastapi\n\n  web:\n    port: 3000  # note\n\njobs: {}  # batch\n" in out
    assert out.startswith("# header comment\n")


def test_insert_into_empty_section_keeps_its_description() -> None:
    out = insert_component(DOC, "jobs", "nightly", "template: python-job\n")
    assert "jobs:   # batch\n  nightly:\n    template: python-job\n\n# overrides comment" in out


def test_missing_section_goes_before_overrides() -> None:
    out = insert_component(DOC, "workers", "mailer", "instances: 1\n")
    assert "jobs: {}  # batch\n\nworkers:\n  mailer:\n    instances: 1\n\n# overrides comment belongs" in out
    assert out.index("workers:") < out.index("overrides:")


def test_missing_section_without_overrides_goes_at_end() -> None:
    assert insert_component("product: x\n", "jobs", "a", "x: 1\n") == "product: x\n\njobs:\n  a:\n    x: 1\n"


def test_delete_first_and_last_in_section() -> None:
    no_api = delete_component(DOC, "apis", "api")
    assert no_api is not None
    assert "apis:  # backends\n  search:\n    template: fastapi\n\njobs: {}" in no_api
    no_search = delete_component(DOC, "apis", "search")
    assert no_search is not None
    assert "    # a comment inside api\n\njobs: {}" in no_search


def test_delete_last_component_empties_section() -> None:
    once = delete_component(DOC, "apis", "api")
    assert once is not None
    twice = delete_component(once, "apis", "search")
    assert twice is not None
    assert "apis: {}  # backends\n\njobs: {}  # batch\n" in twice


def test_delete_only_looks_in_the_given_section() -> None:
    assert delete_component(DOC, "jobs", "api") is None
    assert delete_component(DOC, "workers", "api") is None


def test_new_product_round_trips_through_add_and_remove() -> None:
    """Adding one component of each kind and removing it again restores the file exactly."""
    original = PRODUCT_HEADER.format(product="shop", team="t", envs="dev, prod")
    text = original
    sections = {"app": "apps", "api": "apis", "job": "jobs", "worker": "workers", "function": "functions"}
    for kind, section in sections.items():
        snippet = SNIPPETS[kind].format(template="t", product="shop", name=f"my-{kind}", org="acme")
        text = insert_component(text, section, f"my-{kind}", snippet)
    for kind, section in sections.items():
        out = delete_component(text, section, f"my-{kind}")
        assert out is not None
        text = out
    assert text == original
