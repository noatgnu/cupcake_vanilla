import json
from decimal import Decimal

import pytest
from choux.draft import Draft
from choux.draft.entities import (
    EMPTY_LEGEND,
    amount,
    concentration,
    duration,
    file_attachment,
    go_to_step,
    image,
    new_guid,
    note,
    number_text,
    reagent,
    temperature,
)


@pytest.mark.parametrize(
    "value, expected",
    [(50, "50"), (50.0, "50"), (0.0005, "0.0005"), ("1.50", "1.5"), (Decimal("1E+3"), "1000"), (-0.0, "0")],
)
def test_number_text_formats_like_the_editor(value, expected):
    """Number text formats like the editor."""
    assert number_text(value) == expected


def test_number_text_rejects_non_finite_values():
    """Number text rejects non finite values."""
    with pytest.raises(ValueError):
        number_text(float("inf"))


def test_new_guid_is_32_upper_hex_characters():
    """New guid is 32 upper hex characters."""
    guid = new_guid()
    assert len(guid) == 32
    assert guid == guid.upper()
    int(guid, 16)


def test_amount_has_every_editor_field():
    """Amount has every editor field."""
    entity = amount(50, unit=1, label="buffer")
    assert entity.type == "amount"
    assert set(entity.data) == {"amount", "error", "guid", "id", "label", "scientificNotation", "unit"}
    assert entity.data["amount"] == "50"
    assert entity.data["unit"] == 1


def test_temperature_defaults_to_celsius():
    """Temperature defaults to celsius."""
    assert temperature(4).data["unit"] == 10
    assert "error_temperature" in temperature(4).data


def test_concentration_uses_its_own_error_field():
    """Concentration uses its own error field."""
    assert "error_concentration" in concentration(4, unit=14).data


def test_duration_rounds_to_whole_seconds_and_has_timer_fields():
    """Duration rounds to whole seconds and has timer fields."""
    entity = duration(299.6, label="spin")
    assert entity.data["duration"] == 300
    assert entity.data["preset"] == []
    assert entity.data["pause"] is None
    assert entity.data["start"] is None


def test_file_attachment_uses_upload_details(uploaded_file):
    """File attachment uses upload details."""
    entity = file_attachment(uploaded_file)
    assert entity.type == "file"
    assert not entity.is_atomic
    assert entity.data["id"] == uploaded_file.id
    assert entity.data["size"] == 32
    assert entity.data["source"] == uploaded_file.source


def test_image_uses_upload_size_and_empty_legend(uploaded_image):
    """Image uses upload size and empty legend."""
    entity = image(uploaded_image)
    assert entity.type == "image"
    assert entity.is_atomic
    assert entity.mutability == "IMMUTABLE"
    assert (entity.data["width"], entity.data["height"]) == (640, 480)
    assert entity.data["legend"] == EMPTY_LEGEND


def test_image_caption_is_stored_as_draft_text(uploaded_image):
    """Image caption is stored as draft text."""
    caption = Draft().paragraph("Figure 1")
    legend = json.loads(image(uploaded_image, caption=caption).data["legend"])
    assert legend["blocks"][0]["text"] == "Figure 1"


def test_image_without_size_is_rejected(uploaded_file):
    """Image without size is rejected."""
    with pytest.raises(ValueError):
        image(uploaded_file)


def test_note_holds_a_draft():
    """Note holds a draft."""
    entity = note(Draft().paragraph("Keep on ice"))
    assert entity.is_atomic
    assert entity.data["blocks"][0]["text"] == "Keep on ice"


def test_go_to_step_references_a_step():
    """Go to step references a step."""
    assert go_to_step("A" * 32, "repeat").data["step_guid"] == "A" * 32


SEARCH_ITEM = {
    "id": 1144,
    "name": "Quick Ligation Kit - 30 rxns",
    "mol_weight": 0,
    "linfor": "",
    "url": "https://www.neb.com/M2200",
    "sku": "M2200S",
    "vendor": {
        "name": "New England Biolabs",
        "affiliation": None,
        "username": None,
        "link": "https://www.neb.com/",
        "image": {"source": "https://www.protocols.io/img/vendors/2.png", "placeholder": None},
    },
    "is_citeab": False,
}


def test_reagent_from_search_result_fills_editor_fields():
    """Reagent from search result fills editor fields."""
    entity = reagent(SEARCH_ITEM)
    assert entity.type == "reagents"
    assert not entity.is_atomic
    data = entity.data
    assert (data["id"], data["sku"], data["cas_number"], data["rrid"]) == (1144, "M2200S", "", "")
    assert len(data["guid"]) == 32
    assert data["vendor"] == {
        "id": 0,
        "name": "New England Biolabs",
        "link": "https://www.neb.com/",
        "is_requested": False,
        "image": {
            "source": "https://www.protocols.io/img/vendors/2.png",
            "placeholder": "/img/vendors/placeholder.png",
        },
    }
    assert (data["is_public"], data["can_edit"]) == (True, False)


def test_reagent_keeps_existing_guid_and_vendor_id():
    """Reagent keeps existing guid and vendor id."""
    item = {**SEARCH_ITEM, "guid": "4107467F341F11EE9D4302C0B41BC903", "vendor": {"id": 31, "name": "Fisher"}}
    data = reagent(item).data
    assert data["guid"] == "4107467F341F11EE9D4302C0B41BC903"
    assert data["vendor"]["id"] == 31


@pytest.mark.parametrize("item", [{"name": "x"}, {"id": 5}, {"id": 0, "name": "x"}])
def test_reagent_needs_id_and_name(item):
    """Reagent needs id and name."""
    with pytest.raises(ValueError):
        reagent(item)
