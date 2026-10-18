import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from choux import Draft, ProtocolsIO, RateLimiter, Step, chain, records
from choux.draft import amount, duration
from choux.exceptions import APIError, DraftValidationError, RateLimitError, UploadError

API = "https://www.protocols.io/api"
STORAGE = "https://protocols-files.s3.amazonaws.com/"


@pytest.fixture
def sleeps():
    """Delays the client and rate limiter would have slept for."""
    return []


@pytest.fixture
def client(sleeps):
    """A client whose waits are recorded instead of slept."""
    limiter = RateLimiter(1000, 60, sleep=sleeps.append)
    with ProtocolsIO("token", rate_limiter=limiter, sleep=sleeps.append, backoff=1.0) as instance:
        yield instance


@pytest.fixture
def api():
    """A mocked protocols.io API."""
    with respx.mock(assert_all_called=False) as router:
        yield router


def ok(**fields):
    """Return a successful API response carrying ``fields``."""
    return httpx.Response(200, json={"status_code": 0, **fields})


def sent_json(route, index=0):
    """Return the JSON body of a request sent to a mocked route."""
    return json.loads(route.calls[index].request.content)


def test_requires_a_token():
    """Requires a token."""
    with pytest.raises(ValueError):
        ProtocolsIO("")


def test_sends_the_bearer_token(client, api):
    """Sends the bearer token."""
    route = api.get(f"{API}/v3/session/profile").mock(return_value=ok(user={"username": "someone"}))
    assert client.get_profile() == {"username": "someone"}
    assert route.calls[0].request.headers["Authorization"] == "Bearer token"


def test_given_http_client_is_used_and_left_open(api):
    """Given http client is used and left open."""
    api.get(f"{API}/v3/session/profile").mock(return_value=ok(user={}))
    http_client = httpx.Client()
    with ProtocolsIO("token", http_client=http_client) as instance:
        instance.get_profile()
    assert not http_client.is_closed
    http_client.close()


def test_own_http_client_is_closed():
    """Own http client is closed."""
    instance = ProtocolsIO("token")
    instance.close()
    assert instance.http.is_closed


def test_non_zero_status_code_raises(client, api):
    """Non zero status code raises."""
    api.post(f"{API}/v3/files").mock(
        return_value=httpx.Response(200, json={"status_code": 1, "error_message": "Missing parameter"})
    )
    with pytest.raises(APIError) as raised:
        client.request("POST", "/v3/files", json={})
    assert raised.value.status_code == 1
    assert "Missing parameter" in str(raised.value)


def test_http_error_raises(client, api):
    """Http error raises."""
    api.get(f"{API}/v4/protocols/1").mock(
        return_value=httpx.Response(404, json={"status_code": 404, "status_text": "protocol does not exist"})
    )
    with pytest.raises(APIError) as raised:
        client.get_protocol(1)
    assert raised.value.http_status == 404
    assert "protocol does not exist" in str(raised.value)


def test_non_json_body_raises(client, api):
    """Non json body raises."""
    api.get(f"{API}/v3/session/profile").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(APIError):
        client.get_profile()


def test_retries_after_rate_limit(client, api, sleeps):
    """Retries after rate limit."""
    api.get(f"{API}/v3/session/profile").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(503),
            ok(user={}),
        ]
    )
    assert client.get_profile() == {}
    assert sleeps == [7.0, 2.0]


def test_gives_up_after_max_retries(client, api, sleeps):
    """Gives up after max retries."""
    api.get(f"{API}/v3/session/profile").mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimitError):
        client.get_profile()
    assert sleeps == [1.0, 2.0, 4.0]


def test_retries_connection_failures(client, api, sleeps):
    """Retries connection failures."""
    api.get(f"{API}/v3/session/profile").mock(side_effect=[httpx.ConnectError("down"), ok(user={})])
    assert client.get_profile() == {}
    assert sleeps == [1.0]


def test_connection_failure_after_retries_raises(client, api):
    """Connection failure after retries raises."""
    api.get(f"{API}/v3/session/profile").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(APIError) as raised:
        client.get_profile()
    assert "could not reach" in str(raised.value)


def test_every_request_waits_for_the_rate_limiter(api):
    """Every request waits for the rate limiter."""
    acquired = []

    class CountingLimiter(RateLimiter):
        def acquire(self):
            acquired.append(True)
            return 0.0

    api.get(f"{API}/v3/session/profile").mock(return_value=ok(user={}))
    with ProtocolsIO("token", rate_limiter=CountingLimiter()) as instance:
        instance.get_profile()
    assert acquired == [True]


def test_save_steps_sends_draft_json(client, api):
    """Save steps sends draft json."""
    route = api.post(f"{API}/v4/protocols/340067/steps").mock(return_value=ok(payload=None))
    steps = chain([Step(Draft().paragraph("Spin for ", duration(300))), Step("Done", section="End")])
    assert client.save_steps(340067, steps) == []
    sent = sent_json(route)["steps"]
    assert sent[1]["previous_guid"] == sent[0]["guid"]
    assert json.loads(sent[0]["step"])["entityMap"]["0"]["type"] == "duration"


def test_save_steps_refuses_invalid_content_before_sending(client, api):
    """Save steps refuses invalid content before sending."""
    route = api.post(f"{API}/v4/protocols/340067/steps").mock(return_value=ok(payload=None))
    broken = Draft().paragraph(duration(300)).to_dict()
    del broken["entityMap"]["0"]["data"]["preset"]
    with pytest.raises(DraftValidationError) as raised:
        client.save_steps(340067, [Step(broken)])
    assert raised.value.issues[0].path == "steps[0].step.entityMap[0].data.preset"
    assert not route.called


def test_save_steps_can_skip_validation(client, api):
    """Save steps can skip validation."""
    route = api.post(f"{API}/v4/protocols/340067/steps").mock(return_value=ok(payload=None))
    broken = Draft().paragraph(duration(300)).to_dict()
    del broken["entityMap"]["0"]["data"]["preset"]
    client.save_steps(340067, [Step(broken)], validate=False)
    assert route.call_count == 1


def test_save_steps_checks_units(client):
    """Save steps checks units."""
    with pytest.raises(DraftValidationError):
        client.save_steps(340067, [Step(Draft().paragraph(amount(5, unit=99)))], units={1})


def test_save_steps_checks_unit_kind_with_unit_records(client):
    """Save steps checks unit kind with unit records."""
    units = [{"id": 10, "type_id": 24, "name": "°C"}]
    with pytest.raises(DraftValidationError) as raised:
        client.save_steps(340067, [Step(Draft().paragraph(amount(5, unit=10)))], units=units)
    assert raised.value.issues[0].message == "unit id 10 is not a unit for amount"


def test_save_steps_returns_warnings(client, api):
    """Save steps returns warnings."""
    api.post(f"{API}/v4/protocols/340067/steps").mock(return_value=ok(payload=None))
    content = Draft().paragraph("x", duration(10)).to_dict()
    content["blocks"][0]["text"] = "xy"
    issues = client.save_steps(340067, [Step(content)])
    assert [issue.is_error for issue in issues] == [False]


def test_get_steps_returns_payload(client, api):
    """Get steps returns payload."""
    route = api.get(f"{API}/v4/protocols/340067/steps").mock(return_value=ok(payload=[{"guid": "A"}]))
    assert client.get_steps(340067) == [{"guid": "A"}]
    assert dict(route.calls[0].request.url.params) == {"content_format": "json"}


def test_delete_steps(client, api):
    """Delete steps."""
    route = api.delete(f"{API}/v4/protocols/340067/steps").mock(return_value=ok())
    client.delete_steps(340067, ["A" * 32])
    assert sent_json(route) == {"steps": ["A" * 32]}


def test_update_protocol_serialises_and_validates_rich_text(client, api):
    """Update protocol serialises and validates rich text."""
    route = api.put(f"{API}/v4/protocols/340067").mock(return_value=ok())
    client.update_protocol(340067, title="Lysis", description=Draft().paragraph("About"))
    sent = sent_json(route)
    assert sent["title"] == "Lysis"
    assert json.loads(sent["description"])["blocks"][0]["text"] == "About"


def test_update_protocol_refuses_invalid_rich_text(client, api):
    """Update protocol refuses invalid rich text."""
    route = api.put(f"{API}/v4/protocols/340067").mock(return_value=ok())
    with pytest.raises(DraftValidationError):
        client.update_protocol(340067, description=Draft().paragraph(amount(5, unit=99)), units={1})
    assert not route.called


def prepare_response():
    """Return a prepare file upload response for a PNG image."""
    return ok(
        formData={
            "key": "bk3aebuzf7.png",
            "s3_bucket": "protocols-files",
            "AWSAccessKeyId": "id",
            "Policy": "policy",
            "Signature": "signature",
            "ContentType": "image/png",
            "acl": "public-read",
        },
        metaData={"file_id": "1401860", "file_type": "31", "thumb_url": "https://www.protocols.io/img/png.png"},
    )


def test_upload_file_runs_prepare_store_and_verify(client, api):
    """Upload file runs prepare store and verify."""
    prepare = api.post(f"{API}/v3/files").mock(return_value=prepare_response())
    storage = api.post(STORAGE).mock(return_value=httpx.Response(204))
    verify = api.put(f"{API}/v3/files/1401860").mock(return_value=ok())
    uploaded = client.upload_file("gel.png", b"png-bytes", width=640, height=480)
    assert sent_json(prepare) == {"filename": "gel.png", "width": 640, "height": 480}
    storage_request = storage.calls[0].request
    assert "Authorization" not in storage_request.headers
    body = storage_request.content
    assert b"max-age=31536000" in body
    assert b"public-read" in body
    assert body.index(b'name="Policy"') < body.index(b'name="file"')
    assert verify.called
    assert uploaded.id == 1401860
    assert b"files/bk3aebuzf7.png" in body
    assert uploaded.key == "files/bk3aebuzf7.png"
    assert uploaded.source == "https://content.protocols.io/files/bk3aebuzf7.png"
    assert uploaded.raw_source == "https://protocols-files.s3.amazonaws.com/files/bk3aebuzf7.png"
    assert uploaded.size == len(b"png-bytes")
    assert uploaded.is_image


def test_upload_file_fails_when_storage_rejects_it(client, api):
    """Upload file fails when storage rejects it."""
    api.post(f"{API}/v3/files").mock(return_value=prepare_response())
    api.post(STORAGE).mock(return_value=httpx.Response(403, text="<Error>AccessDenied</Error>"))
    verify = api.put(f"{API}/v3/files/1401860").mock(return_value=ok())
    with pytest.raises(UploadError):
        client.upload_file("gel.png", b"png-bytes")
    assert not verify.called


def test_upload_file_fails_when_storage_is_unreachable(client, api):
    """Upload file fails when storage is unreachable."""
    api.post(f"{API}/v3/files").mock(return_value=prepare_response())
    api.post(STORAGE).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(UploadError):
        client.upload_file("gel.png", b"png-bytes")


def test_create_record_uses_a_form_with_the_folder(client, api):
    """Create record uses a form with the folder."""
    route = api.post(f"{API}/v3/records").mock(return_value=ok(record={"guid": "R"}))
    assert client.create_record("my-protocol", folder_guid="F" * 32) == {"guid": "R"}
    assert parse_qs(route.calls[0].request.content.decode()) == {
        "protocol_uri": ["my-protocol"],
        "folder_data.guid": ["F" * 32],
    }


def test_save_record_sends_a_json_stack(client, api):
    """Save record sends a json stack."""
    route = api.put(f"{API}/v3/records/R").mock(return_value=ok())
    client.save_record("R", [records.set_title("Run 1"), records.mark_step("S" * 32, checked=True)])
    assert sent_json(route) == {
        "stack": [
            {"type": "base", "data": {"title": "Run 1"}},
            {"type": "step", "data": {"guid": "S" * 32, "is_checked": 1}},
        ]
    }


def test_get_record(client, api):
    """Get record."""
    route = api.get(f"{API}/v4/records/R").mock(return_value=ok(payload={"record": {"guid": "R"}}))
    assert client.get_record("R", with_protocol=True) == {"guid": "R"}
    assert dict(route.calls[0].request.url.params) == {"content_format": "json", "with_protocol": "1"}


def test_trash_and_restore(client, api):
    """Trash and restore."""
    api.put(f"{API}/v3/filemanager/trash").mock(return_value=ok(deleted=[5]))
    api.delete(f"{API}/v3/filemanager/trash").mock(return_value=ok(restored=[5]))
    assert client.trash([5]) == [5]
    assert client.restore([5]) == [5]


def test_publish_can_issue_only_a_doi(client, api):
    """Publish can issue only a doi."""
    route = api.post(f"{API}/v3/protocols/my-protocol/publish").mock(return_value=ok())
    client.publish("my-protocol", doi_only=True)
    assert dict(route.calls[0].request.url.params) == {"prepublish": "1"}


def test_list_and_search_workspaces(client, api):
    """List and search workspaces."""
    api.get(f"{API}/v3/workspaces").mock(return_value=ok(items=[{"uri": "lab"}], pagination={}))
    api.get(f"{API}/v4/filemanager/workspaces/lab/search").mock(
        return_value=ok(payload={"items": [], "pagination": {}})
    )
    assert client.list_workspaces()["items"] == [{"uri": "lab"}]
    assert client.search_workspace("lab", page_size=5) == {"items": [], "pagination": {}}


def test_search_reagents(client, api):
    """Search reagents."""
    route = api.get(f"{API}/v3/reagents").mock(
        return_value=ok(items=[{"id": 1144, "name": "Quick Ligation Kit"}], pagination={"total_results": 1})
    )
    result = client.search_reagents(" ligation ", citeab=False, page_size=5)
    assert result == {"items": [{"id": 1144, "name": "Quick Ligation Kit"}], "pagination": {"total_results": 1}}
    assert dict(route.calls[0].request.url.params) == {
        "key": "ligation",
        "page_size": "5",
        "page_id": "1",
        "is_citeab": "false",
    }


def test_search_reagents_needs_a_key(client):
    """Search reagents needs a key."""
    with pytest.raises(ValueError):
        client.search_reagents("  ")


def test_get_materials(client, api):
    """Get materials."""
    api.get(f"{API}/v3/protocols/340067/materials").mock(return_value=ok(materials=[{"id": 1}]))
    assert client.get_materials(340067) == [{"id": 1}]


def test_record_mark_step_needs_a_flag():
    """Record mark step needs a flag."""
    with pytest.raises(ValueError):
        records.mark_step("S")


def test_record_notes():
    """Record notes."""
    assert records.add_note("hi", step_id=4) == {"type": "notes", "data": {"id": None, "note": "hi", "step_id": 4}}
    assert records.edit_note(9, "new") == {"type": "notes", "data": {"id": 9, "note": "new"}}
