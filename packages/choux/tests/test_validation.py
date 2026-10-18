import json

import pytest
from choux.draft import Draft, amount, duration, file_attachment, image, note, reagent, temperature
from choux.draft.validation import Severity, ensure_valid, validate_draft, validate_step_fields
from choux.exceptions import DraftValidationError

GUID = "046CAB9235C6447AA6A39D4BEA5966F9"


def block(text, block_type="unstyled", ranges=None, key="a1b2c"):
    """Return a raw Draft.js block."""
    return {
        "key": key,
        "text": text,
        "type": block_type,
        "depth": 0,
        "inlineStyleRanges": [],
        "entityRanges": ranges or [],
        "data": {},
    }


def errors(issues):
    """Return the path and message of each error."""
    return [(issue.path, issue.message) for issue in issues if issue.is_error]


def warnings(issues):
    """Return the path and message of each warning."""
    return [(issue.path, issue.message) for issue in issues if issue.severity is Severity.WARNING]


def test_built_content_is_valid(uploaded_image, uploaded_file):
    """Built content is valid."""
    draft = (
        Draft()
        .paragraph("Spin for ", duration(300, "spin"), " using ", amount(50, 1, "buffer"), " at ", temperature(4), ".")
        .block_entity(image(uploaded_image, caption=Draft().paragraph("Figure 1")))
        .paragraph("Layout: ", file_attachment(uploaded_file))
        .block_entity(note(Draft().paragraph("Keep on ice")))
    )
    assert validate_draft(draft, units={1, 10}) == []


def test_entities_without_editor_fields_are_errors():
    """Entities without editor fields are errors."""
    draft = {
        "blocks": [block("Spin for 300 s", ranges=[{"offset": 9, "length": 5, "key": 0}])],
        "entityMap": {"0": {"type": "duration", "mutability": "IMMUTABLE", "data": {"duration": 300, "label": "spin"}}},
    }
    found = errors(validate_draft(draft))
    assert ("entityMap[0].data.preset", "is missing") in found
    assert ("entityMap[0].data.guid", "is missing") in found
    assert ("blocks[0].entityRanges[0]", "duration must cover exactly one placeholder character") in found


def test_numeric_quantity_must_be_text():
    """Numeric quantity must be text."""
    entity = amount(50, 1).to_dict()
    entity["data"]["amount"] = 50
    draft = {"blocks": [block(" ", ranges=[{"offset": 0, "length": 1, "key": 0}])], "entityMap": {"0": entity}}
    assert errors(validate_draft(draft)) == [("entityMap[0].data.amount", "expected number_text, got int")]


def test_imageblock_type_is_unsupported():
    """Imageblock type is unsupported."""
    draft = {
        "blocks": [block(" ", "atomic", [{"offset": 0, "length": 1, "key": 0}])],
        "entityMap": {"0": {"type": "imageblock", "mutability": "IMMUTABLE", "data": {"source": "x"}}},
    }
    assert errors(validate_draft(draft)) == [("entityMap[0].type", "unsupported entity type 'imageblock'")]


def test_file_in_an_atomic_block_is_an_error(uploaded_file):
    """File in an atomic block is an error."""
    draft = {
        "blocks": [block(" ", "atomic", [{"offset": 0, "length": 1, "key": 0}])],
        "entityMap": {"0": file_attachment(uploaded_file).to_dict()},
    }
    assert errors(validate_draft(draft)) == [
        ("blocks[0].entityRanges[0]", "file must be placed inside text, not in an atomic block")
    ]


def test_image_inside_text_is_an_error(uploaded_image):
    """Image inside text is an error."""
    draft = {
        "blocks": [block(" ", ranges=[{"offset": 0, "length": 1, "key": 0}])],
        "entityMap": {"0": image(uploaded_image).to_dict()},
    }
    assert errors(validate_draft(draft)) == [("blocks[0].entityRanges[0]", "image must be placed in an atomic block")]


def test_empty_image_legend_text_is_an_error(uploaded_image):
    """Empty image legend text is an error."""
    entity = image(uploaded_image).to_dict()
    entity["data"]["legend"] = ""
    draft = {"blocks": [block(" ", "atomic", [{"offset": 0, "length": 1, "key": 0}])], "entityMap": {"0": entity}}
    assert errors(validate_draft(draft)) == [("entityMap[0].data.legend", "expected draft_text, got str")]


def test_invalid_caption_content_is_reported(uploaded_image):
    """Invalid caption content is reported."""
    entity = image(uploaded_image).to_dict()
    entity["data"]["legend"] = json.dumps({"blocks": [{"key": "x", "text": 3}], "entityMap": {}})
    draft = {"blocks": [block(" ", "atomic", [{"offset": 0, "length": 1, "key": 0}])], "entityMap": {"0": entity}}
    assert errors(validate_draft(draft)) == [("entityMap[0].data.legend.blocks[0].text", "must be a string")]


def test_entity_on_visible_text_is_a_warning():
    """Entity on visible text is a warning."""
    draft = Draft().paragraph("x", duration(10)).to_dict()
    draft["blocks"][0]["text"] = "xy"
    issues = validate_draft(draft)
    assert errors(issues) == []
    assert warnings(issues) == [
        ("blocks[0].entityRanges[0]", "duration covers visible text, which is shown next to its value")
    ]


def test_unknown_unit_is_an_error_when_units_are_given():
    """Unknown unit is an error when units are given."""
    draft = Draft().paragraph(amount(5, unit=999))
    assert validate_draft(draft) == []
    assert errors(validate_draft(draft, units={1, 2})) == [
        ("entityMap[0].data.unit", "unit id 999 is not available in this protocol")
    ]


def test_structure_problems_are_reported():
    """Structure problems are reported."""
    draft = {
        "blocks": [
            block("ab", block_type="heading", key="k"),
            {**block("cd", key="k"), "inlineStyleRanges": [{"offset": 1, "length": 5, "style": "underline"}]},
            block("ef", ranges=[{"offset": 0, "length": 1, "key": 7}], key="m"),
        ],
        "entityMap": {"3": duration(1).to_dict()},
    }
    issues = validate_draft(draft)
    assert set(errors(issues)) == {
        ("blocks[0].type", "unknown block type 'heading'"),
        ("blocks[1].key", "duplicate block key 'k'"),
        ("blocks[1].inlineStyleRanges[0].style", "unsupported style 'underline'"),
        ("blocks[1].inlineStyleRanges[0]", "offset and length must lie inside the block text"),
        ("blocks[2].entityRanges[0].key", "no entity with key 7"),
    }
    assert warnings(issues) == [("entityMap[3]", "entity is not referenced by any block")]


def test_atomic_block_needs_exactly_one_entity():
    """Atomic block needs exactly one entity."""
    draft = {"blocks": [block(" ", "atomic")], "entityMap": {}}
    assert errors(validate_draft(draft)) == [("blocks[0].entityRanges", "an atomic block must hold exactly one entity")]


def test_known_unchecked_entities_only_warn():
    """Known unchecked entities only warn."""
    draft = {
        "blocks": [block(" ", "atomic", [{"offset": 0, "length": 1, "key": 0}])],
        "entityMap": {"0": {"type": "equipment", "mutability": "IMMUTABLE", "data": {"name": "Centrifuge"}}},
    }
    issues = validate_draft(draft)
    assert errors(issues) == []
    assert warnings(issues) == [("entityMap[0].type", "equipment entities are passed through without field checks")]


def test_nested_note_content_is_checked():
    """Nested note content is checked."""
    content = Draft().paragraph(duration(5)).to_dict()
    del content["entityMap"]["0"]["data"]["preset"]
    draft = {
        "blocks": [block(" ", "atomic", [{"offset": 0, "length": 1, "key": 0}])],
        "entityMap": {"0": {"type": "notes", "mutability": "IMMUTABLE", "data": content}},
    }
    assert errors(validate_draft(draft)) == [("entityMap[0].data.entityMap[0].data.preset", "is missing")]


@pytest.mark.parametrize(
    "content, expected",
    [
        ("{not json", "content"),
        ({"blocks": []}, "blocks"),
        ({"blocks": [block("a")], "entityMap": "x"}, "entityMap"),
        ([], "content"),
    ],
)
def test_unusable_documents_are_rejected(content, expected):
    """Unusable documents are rejected."""
    assert [issue.path for issue in validate_draft(content)] == [expected]


def test_empty_list_entity_map_is_accepted():
    """Empty list entity map is accepted."""
    assert validate_draft({"blocks": [block("a")], "entityMap": []}) == []


def test_json_text_is_accepted():
    """Json text is accepted."""
    assert validate_draft(Draft().paragraph("a").to_json()) == []


def test_ensure_valid_raises_with_all_issues():
    """Ensure valid raises with all issues."""
    draft = {"blocks": [block("a", block_type="heading")], "entityMap": {"0": duration(1).to_dict()}}
    with pytest.raises(DraftValidationError) as raised:
        ensure_valid(draft)
    assert len(raised.value.issues) == 2
    assert "unknown block type" in str(raised.value)


def test_ensure_valid_returns_warnings():
    """Ensure valid returns warnings."""
    draft = Draft().paragraph("x", duration(10)).to_dict()
    draft["blocks"][0]["text"] = "xy"
    assert len(ensure_valid(draft)) == 1


@pytest.mark.parametrize(
    "guid, previous, color, expected",
    [
        (GUID, None, "#84CE84", []),
        (GUID.lower(), None, None, ["guid"]),
        (GUID, "nope", None, ["previous_guid"]),
        (GUID, GUID, None, ["previous_guid"]),
        (GUID, None, "green", ["section_color"]),
    ],
)
def test_step_fields(guid, previous, color, expected):
    """Step fields."""
    assert [issue.path for issue in validate_step_fields(guid, previous, color)] == expected


def test_reagent_from_search_is_valid():
    """Reagent from search is valid."""
    item = {"id": 1144, "name": "Quick Ligation Kit", "sku": "M2200S", "vendor": {"name": "NEB"}}
    assert validate_draft(Draft().paragraph("Ligate with ", reagent(item), ".")) == []


def test_reagent_vendor_fields_are_checked():
    """Reagent vendor fields are checked."""
    draft = Draft().paragraph(reagent({"id": 1, "name": "Water"})).to_dict()
    del draft["entityMap"]["0"]["data"]["vendor"]["is_requested"]
    assert errors(validate_draft(draft)) == [("entityMap[0].data.vendor.is_requested", "is missing")]


def test_unit_records_check_the_unit_kind():
    """Unit records check the unit kind."""
    units = [{"id": 1, "type_id": 3}, {"id": 10, "type_id": 24}]
    assert validate_draft(Draft().paragraph(amount(5, 1), temperature(4, 10)), units=units) == []
    assert errors(validate_draft(Draft().paragraph(temperature(4, 1)), units=units)) == [
        ("entityMap[0].data.unit", "unit id 1 is not a unit for temperature")
    ]
