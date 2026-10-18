import pytest
from choux.units import match_unit, normalise, unit_kind

UNITS = [
    {"id": 1, "type_id": 3, "name": "µL", "aliases": ["µl", "uL", "ul", "microlitre", "microliter"]},
    {"id": 2, "type_id": 3, "name": "mL", "aliases": ["ml", "milliliter"]},
    {"id": 24, "type_id": 3, "name": "μV", "aliases": []},
    {"id": 10, "type_id": 24, "name": "°C", "aliases": ["Celsius", "C"]},
    {"id": 28, "type_id": 25, "name": "millimolar (mM)", "aliases": ["mM"]},
    {"id": 201, "type_id": 32, "name": "mm", "aliases": ["mm"]},
    {"id": 34, "type_id": 30, "name": "x g", "aliases": ["xg"]},
    {"id": 99, "type_id": 3, "name": "old", "aliases": [], "deleted": True},
    {"id": 98, "type_id": 3, "name": "fixed", "aliases": [], "read_only": 1},
]


@pytest.mark.parametrize(
    "text, kind, expected",
    [
        ("µL", None, 1),
        ("uL", "amount", 1),
        ("μL", "amount", 1),
        (" microliter ", "amount", 1),
        ("UL", "amount", 1),
        ("ML", "amount", 2),
        ("uV", "amount", 24),
        ("C", "temperature", 10),
        ("mM", "concentration", 28),
        ("mm", None, 201),
        ("xg", None, 34),
        ("X G", None, 34),
    ],
)
def test_match_unit(text, kind, expected):
    """Match unit."""
    assert match_unit(text, UNITS, kind=kind)["id"] == expected


@pytest.mark.parametrize("text, kind", [("", None), ("furlong", None), ("C", "amount"), ("old", None), ("fixed", None)])
def test_match_unit_without_a_match(text, kind):
    """Match unit without a match."""
    assert match_unit(text, UNITS, kind=kind) is None


def test_ambiguous_case_insensitive_match_is_refused():
    """Ambiguous case insensitive match is refused."""
    assert match_unit("MM", UNITS) is None


def test_unknown_kind_is_rejected():
    """Unknown kind is rejected."""
    with pytest.raises(ValueError):
        match_unit("uL", UNITS, kind="volume")


def test_normalise():
    """Normalise."""
    assert normalise(" µ L ") == "uL"


def test_unit_kind():
    """Unit kind."""
    assert [unit_kind(unit) for unit in UNITS[:7]] == [
        "amount",
        "amount",
        "amount",
        "temperature",
        "concentration",
        None,
        None,
    ]
