#!/bin/bash
# Exports requirements.txt from the Poetry lock file with the bundled packages/ dependencies
# written relative to the repository root instead of the exporting machine's absolute paths.
set -euo pipefail

cd "$(dirname "$0")/.."

poetry export --without-hashes --format requirements.txt --output requirements.txt
sed -i -E 's#^-e file://[^ ]*/packages/#-e ./packages/#' requirements.txt
