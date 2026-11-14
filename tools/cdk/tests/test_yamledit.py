from cdk.yamledit import delete_component, insert_component

DOC = """\
# header comment
product: orders
team: commerce

components:
  api:
    kind: api
    # a comment inside api

  job1:
    kind: job

# overrides comment belongs to the next section
overrides:
  prod:
    api: { min_instances: 2 }
"""


def test_insert_keeps_comments_and_spacing() -> None:
    out = insert_component(DOC, "web", "kind: web\npublic: true  # note\n")
    assert "  job1:\n    kind: job\n\n  web:\n    kind: web\n    public: true  # note\n\n# overrides comment" in out
    assert out.startswith("# header comment\n")


def test_insert_into_empty_block() -> None:
    out = insert_component("product: x\n\ncomponents: {}\n\n# tail\n", "a", "kind: job\n")
    assert out == "product: x\n\ncomponents:\n  a:\n    kind: job\n\n# tail\n"


def test_insert_creates_block_when_missing() -> None:
    assert insert_component("product: x\n", "a", "kind: job\n") == "product: x\n\ncomponents:\n  a:\n    kind: job\n"


def test_delete_middle_first_last() -> None:
    no_api = delete_component(DOC, "api")
    assert no_api is not None
    assert "components:\n  job1:\n    kind: job\n\n# overrides comment" in no_api
    no_job = delete_component(DOC, "job1")
    assert no_job is not None
    assert "    # a comment inside api\n\n# overrides comment" in no_job


def test_delete_last_component_leaves_empty_block() -> None:
    once = delete_component(DOC, "api")
    assert once is not None
    twice = delete_component(once, "job1")
    assert twice is not None
    assert "components: {}\n\n# overrides comment" in twice


def test_delete_unknown_returns_none() -> None:
    assert delete_component(DOC, "nope") is None


def test_insert_then_delete_round_trips() -> None:
    out = insert_component(DOC, "web", "kind: web\n")
    assert delete_component(out, "web") == DOC
