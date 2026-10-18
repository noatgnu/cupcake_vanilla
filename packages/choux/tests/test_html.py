import pytest
from choux.draft import Draft, Span, duration, html_to_draft, image, note, validate_draft


def blocks(draft):
    """Return the blocks of a Draft.js document."""
    return draft.to_dict()["blocks"]


def test_paragraphs_become_blocks():
    """Paragraphs become blocks."""
    result = blocks(html_to_draft("<p>First</p><p>Second</p>"))
    assert [block["text"] for block in result] == ["First", "Second"]


def test_plain_text_without_tags_is_one_block():
    """Plain text without tags is one block."""
    assert [block["text"] for block in blocks(html_to_draft("Just text"))] == ["Just text"]


def test_empty_html_still_has_a_block():
    """Empty html still has a block."""
    assert [block["text"] for block in blocks(html_to_draft(""))] == [""]


def test_whitespace_is_collapsed():
    """Whitespace is collapsed."""
    assert blocks(html_to_draft("<p>  Spin \n\n the   sample  </p>"))[0]["text"] == "Spin the sample"


def test_inline_styles_are_kept():
    """Inline styles are kept."""
    block = blocks(html_to_draft("<p><strong>Spin</strong> at <em>4</em> C<sup>o</sup></p>"))[0]
    assert block["text"] == "Spin at 4 Co"
    assert {(style["style"], style["offset"], style["length"]) for style in block["inlineStyleRanges"]} == {
        ("bold", 0, 4),
        ("italic", 8, 1),
        ("sup", 11, 1),
    }


def test_headings_are_bold():
    """Headings are bold."""
    block = blocks(html_to_draft("<h2>Preparation</h2>"))[0]
    assert block["inlineStyleRanges"] == [{"offset": 0, "length": 11, "style": "bold"}]


def test_line_breaks_split_blocks():
    """Line breaks split blocks."""
    assert [block["text"] for block in blocks(html_to_draft("<p>one<br>two</p>"))] == ["one", "two"]


def test_nested_lists_keep_type_and_depth():
    """Nested lists keep type and depth."""
    html = "<ul><li>a</li><li>b<ol><li>c</li></ol></li></ul>"
    result = blocks(html_to_draft(html))
    assert [(block["text"], block["type"], block["depth"]) for block in result] == [
        ("a", "unordered-list-item", 0),
        ("b", "unordered-list-item", 0),
        ("c", "ordered-list-item", 1),
    ]


def test_paragraph_inside_list_item_stays_a_list_item():
    """Paragraph inside list item stays a list item."""
    result = blocks(html_to_draft("<ol><li><p>Mix</p></li></ol>"))
    assert [(block["text"], block["type"]) for block in result] == [("Mix", "ordered-list-item")]


def test_links_become_link_entities():
    """Links become link entities."""
    draft = html_to_draft('<p>See <a href="https://example.org">the <b>paper</b></a> now</p>').to_dict()
    block = draft["blocks"][0]
    assert block["text"] == "See the paper now"
    assert block["entityRanges"] == [{"offset": 4, "length": 9, "key": 0}]
    assert draft["entityMap"]["0"]["data"]["url"] == "https://example.org"


def test_links_without_text_are_dropped():
    """Links without text are dropped."""
    assert html_to_draft('<p>x<a href="https://example.org"> </a></p>').to_dict()["entityMap"] == {}


def test_alignment_is_kept():
    """Alignment is kept."""
    result = blocks(html_to_draft('<p style="text-align: center">Mid</p><p class="ql-align-right">End</p>'))
    assert [block["type"] for block in result] == ["align-center", "align-right"]


def test_tables_become_rows_of_cells():
    """Tables become rows of cells."""
    html = "<table><tr><th>Tube</th><th>Volume</th></tr><tr><td>A</td><td>5 uL</td></tr></table>"
    assert [block["text"] for block in blocks(html_to_draft(html))] == ["Tube | Volume", "A | 5 uL"]


def test_scripts_and_styles_are_ignored():
    """Scripts and styles are ignored."""
    assert [block["text"] for block in blocks(html_to_draft("<style>p{}</style><p>a</p><script>x()</script>"))] == ["a"]


def test_entities_are_decoded():
    """Entities are decoded."""
    assert blocks(html_to_draft("<p>5&nbsp;&micro;L &amp; more</p>"))[0]["text"] == "5 µL & more"


def test_preformatted_text_keeps_spacing():
    """Preformatted text keeps spacing."""
    assert [block["text"] for block in blocks(html_to_draft("<pre>a  b\nc</pre>"))] == ["a  b", "c"]


def test_images_are_dropped_without_a_resolver():
    """Images are dropped without a resolver."""
    assert [block["type"] for block in blocks(html_to_draft('<p>a<img src="x.png">b</p>'))] == ["unstyled"]


def test_images_use_the_resolver(uploaded_image):
    """Images use the resolver."""
    seen = []

    def resolve(src, attributes):
        seen.append((src, attributes.get("alt")))
        return image(uploaded_image)

    draft = html_to_draft('<p>before<img src="gel.png" alt="gel">after</p>', image_resolver=resolve)
    assert seen == [("gel.png", "gel")]
    assert [(block["type"], block["text"]) for block in blocks(draft)] == [
        ("unstyled", "before"),
        ("atomic", " "),
        ("unstyled", "after"),
    ]
    assert validate_draft(draft) == []


def test_resolver_can_skip_images():
    """Resolver can skip images."""
    draft = html_to_draft('<p>a<img src="x.png"></p>', image_resolver=lambda src, attributes: None)
    assert [block["text"] for block in blocks(draft)] == ["a"]


def test_converted_content_is_valid():
    """Converted content is valid."""
    html = (
        '<h1>Lysis</h1><p>Add <b>RIPA</b> buffer, see <a href="https://example.org">kit</a>.</p>'
        "<ul><li>Vortex</li><li>Spin</li></ul><table><tr><td>a</td><td>b</td></tr></table>"
    )
    assert validate_draft(html_to_draft(html)) == []


def test_result_is_a_draft():
    """Result is a draft."""
    assert isinstance(html_to_draft("<p>a</p>"), Draft)


def split_tokens(text):
    """Replace every ``%T%`` in text with a duration entity."""
    parts = []
    for index, piece in enumerate(text.split("%T%")):
        if index:
            parts.append(duration(60))
        parts.append(piece)
    return parts


def test_text_resolver_places_inline_entities():
    """Text resolver places inline entities."""
    draft = html_to_draft("<p>Spin for %T% then %T%.</p>", text_resolver=split_tokens).to_dict()
    block = draft["blocks"][0]
    assert block["text"] == "Spin for   then  ."
    assert [entity["type"] for entity in draft["entityMap"].values()] == ["duration", "duration"]
    assert [entity_range["length"] for entity_range in block["entityRanges"]] == [1, 1]
    assert validate_draft(draft) == []


def test_text_resolver_keeps_surrounding_styles():
    """Text resolver keeps surrounding styles."""

    def resolve(text):
        return [Span(text.upper(), italic=True)]

    block = html_to_draft("<p><b>mix</b></p>", text_resolver=resolve).to_dict()["blocks"][0]
    assert block["text"] == "MIX"
    assert {style["style"] for style in block["inlineStyleRanges"]} == {"bold", "italic"}


def test_text_resolver_block_entities_start_their_own_block():
    """Text resolver block entities start their own block."""
    content = Draft().paragraph("careful")

    def resolve(text):
        before, _, after = text.partition("%NOTE%")
        return [before, note(content), after]

    result = blocks(html_to_draft("<p>before %NOTE% after</p>", text_resolver=resolve))
    assert [(block["type"], block["text"]) for block in result] == [
        ("unstyled", "before"),
        ("atomic", " "),
        ("unstyled", "after"),
    ]


def test_text_resolver_entity_inside_a_link_ends_the_link():
    """Text resolver entity inside a link ends the link."""
    draft = html_to_draft('<p><a href="https://example.org">see %T%</a></p>', text_resolver=split_tokens).to_dict()
    assert [entity["type"] for entity in draft["entityMap"].values()] == ["link", "duration"]
    assert validate_draft(draft) == []


def test_text_resolver_rejects_unknown_parts():
    """Text resolver rejects unknown parts."""
    with pytest.raises(TypeError):
        html_to_draft("<p>a</p>", text_resolver=lambda text: [42])
