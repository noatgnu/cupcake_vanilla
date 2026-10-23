# cupcake-protocols-io

protocols.io integration for [Cupcake](https://github.com/noatgnu/cupcake_vanilla), as a Django app.

- Each user connects their own protocols.io account. Tokens are stored encrypted.
- Browse workspaces, folders and protocols, and import protocols into Cupcake.
- Export Cupcake protocols into protocols.io protocols, with reagent amounts, step times and images.
- Export Cupcake sessions into protocols.io runs, one run per protocol, with step annotations as
  step comments. Steps varied in a session are exported as a copy of the protocol with the varied steps.
- protocols.io reagents and units as external vocabularies for metadata columns.

## Requirements

The app runs inside a Cupcake backend. It uses the Cupcake core (`ccc`), vanilla (`ccv`) and
red velvet (`ccrv`) apps, which are not installed by this package.

## Installation

```
pip install cupcake-protocols-io
```

Add the app after the Cupcake apps:

```python
INSTALLED_APPS = [
    ...,
    "ccc.apps.CccConfig",
    "ccv.apps.CcvConfig",
    "ccrv.apps.CcrvConfig",
    "cupcake_protocols_io.apps.ProtocolsIOConfig",
]
```

Include its URLs under the API prefix and migrate:

```python
urlpatterns += [path("api/v1/", include("cupcake_protocols_io.urls"))]
```

```
python manage.py migrate protocols_io
```

## Settings

| Setting | Default | Use |
|---|---|---|
| `PROTOCOLS_IO_ACCESS_TOKEN` | empty | Server token for imports by users without an account and for the vocabularies |
| `PROTOCOLS_IO_UNITS_PROTOCOL` | empty | Protocol whose unit list is loaded as the unit vocabulary |
| `PROTOCOLS_IO_MAX_UPLOAD_BYTES` | 100 MB | Largest annotation file uploaded to a run |

## Endpoints

All paths are under the API prefix.

| Method | Path | Use |
|---|---|---|
| GET, POST | `protocols-io/account/` | Connection status; connect with an access token |
| DELETE | `protocols-io/account/disconnect/` | Remove the saved account |
| GET | `protocols-io/browse/workspaces/`, `workspace_items/`, `folder_items/`, `search/` | Browse protocols.io |
| POST | `protocols-io/protocols/import/` | Import from an address or DOI link |
| POST | `protocols-io/protocols/import_from_account/` | Import with the user's account |
| POST | `protocols-io/protocols/{id}/export/` | Queue a protocol export |
| GET | `protocols-io/protocols/{id}/exports/` | Earlier exports of a protocol |
| POST | `protocols-io/sessions/{id}/export/` | Queue a session export into runs |
| GET | `protocols-io/sessions/{id}/status/` | How each protocol of a session would be exported |
| GET | `protocols-io/sessions/{id}/runs/` | Runs a session was exported into |

## Tests

From the root of a Cupcake checkout:

```
pytest packages/cupcake-protocols-io/tests
```
