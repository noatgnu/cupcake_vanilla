import json

import pytest
from choux.draft import Draft, bold, duration, hyperlink, image, italic, temperature
from choux.draft.schema import PLACEHOLDER


def test_paragraph_places_inline_entities_on_one_placeholder():
    """Paragraph places inline entities on one placeholder."""
    draft = Draft().paragraph("Spin for ", duration(300), " at ", temperature(4), ".").to_dict()
    block = draft["blocks"][0]
    assert block["text"] == f"Spin for {PLACEHOLDER} at {PLACEHOLDER}."
    assert block["entityRanges"] == [{"offset": 9, "length": 1, "key": 0}, {"offset": 14, "length": 1, "key": 1}]
    assert [draft["entityMap"][key]["type"] for key in ("0", "1")] == ["duration", "temperature"]


def test_styled_spans_produce_style_ranges():
    """Styled spans produce style ranges."""
    block = Draft().paragraph(bold("Spin"), " then ", italic("rest")).to_dict()["blocks"][0]
    assert block["text"] == "Spin then rest"
    assert block["inlineStyleRanges"] == [
        {"offset": 0, "length": 4, "style": "bold"},
        {"offset": 10, "length": 4, "style": "italic"},
    ]


def test_hyperlink_covers_its_text():
    """Hyperlink covers its text."""
    draft = Draft().paragraph("See ", hyperlink("the paper", "https://example.org")).to_dict()
    assert draft["blocks"][0]["entityRanges"] == [{"offset": 4, "length": 9, "key": 0}]
    assert draft["entityMap"]["0"]["data"]["url"] == "https://example.org"


def test_block_entity_creates_an_atomic_block(uploaded_image):
    """Block entity creates an atomic block."""
    block = Draft().block_entity(image(uploaded_image)).to_dict()["blocks"][0]
    assert block["type"] == "atomic"
    assert block["text"] == PLACEHOLDER
    assert block["entityRanges"] == [{"offset": 0, "length": 1, "key": 0}]


def test_atomic_entity_is_refused_inside_text(uploaded_image):
    """Atomic entity is refused inside text."""
    with pytest.raises(ValueError):
        Draft().paragraph("Gel:", image(uploaded_image))


def test_inline_entity_is_refused_as_a_block():
    """Inline entity is refused as a block."""
    with pytest.raises(ValueError):
        Draft().block_entity(duration(60))


def test_unknown_part_is_refused():
    """Unknown part is refused."""
    with pytest.raises(TypeError):
        Draft().paragraph(42)


def test_list_items_use_list_block_types():
    """List items use list block types."""
    blocks = Draft().bullet("one").numbered("two", depth=1).to_dict()["blocks"]
    assert [(block["type"], block["depth"]) for block in blocks] == [
        ("unordered-list-item", 0),
        ("ordered-list-item", 1),
    ]


def test_block_keys_are_unique():
    """Block keys are unique."""
    draft = Draft()
    for index in range(200):
        draft.paragraph(str(index))
    keys = [block["key"] for block in draft.to_dict()["blocks"]]
    assert len(set(keys)) == len(keys)


def test_extend_renumbers_entities():
    """Extend renumbers entities."""
    first = Draft().paragraph("a ", duration(10))
    second = Draft().paragraph("b ", temperature(4))
    merged = first.extend(second).to_dict()
    assert merged["blocks"][1]["entityRanges"][0]["key"] == 1
    assert merged["entityMap"]["1"]["type"] == "temperature"


def test_from_text_makes_one_paragraph_per_line():
    """From text makes one paragraph per line."""
    blocks = Draft.from_text("first\n\n  second  \n").to_dict()["blocks"]
    assert [block["text"] for block in blocks] == ["first", "second"]


def test_from_text_with_blank_text_still_has_a_block():
    """From text with blank text still has a block."""
    assert Draft.from_text("   ").to_dict()["blocks"][0]["text"] == ""


def test_to_json_round_trips():
    """To json round trips."""
    draft = Draft().paragraph("Spin for ", duration(300))
    assert json.loads(draft.to_json()) == draft.to_dict()
