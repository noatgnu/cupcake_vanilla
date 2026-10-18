import json

from choux import Draft, Step, chain
from choux.draft import duration


def test_plain_text_becomes_draft_paragraphs():
    """Plain text becomes draft paragraphs."""
    step = Step("Mix well\nSpin down")
    assert [block["text"] for block in step.draft()["blocks"]] == ["Mix well", "Spin down"]


def test_draft_json_text_is_kept():
    """Draft json text is kept."""
    content = Draft().paragraph("Spin for ", duration(60)).to_json()
    assert Step(content).draft() == json.loads(content)


def test_json_text_that_is_not_a_draft_is_treated_as_plain_text():
    """Json text that is not a draft is treated as plain text."""
    assert Step("[1, 2]").draft()["blocks"][0]["text"] == "[1, 2]"


def test_to_api_serialises_the_draft():
    """To api serialises the draft."""
    step = Step(Draft().paragraph("Spin"), section="Prep", section_color="#84CE84")
    payload = step.to_api()
    assert payload["guid"] == step.guid
    assert payload["previous_guid"] is None
    assert json.loads(payload["step"])["blocks"][0]["text"] == "Spin"
    assert (payload["section"], payload["section_color"], payload["is_substep"]) == ("Prep", "#84CE84", False)


def test_chain_links_steps_in_order():
    """Chain links steps in order."""
    steps = chain([Step("a"), Step("b"), Step("c")])
    assert steps[0].previous_guid is None
    assert steps[1].previous_guid == steps[0].guid
    assert steps[2].previous_guid == steps[1].guid


def test_chain_can_continue_after_an_existing_step():
    """Chain can continue after an existing step."""
    existing = "F" * 32
    assert chain([Step("a")], after=existing)[0].previous_guid == existing
