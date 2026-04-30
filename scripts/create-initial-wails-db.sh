#!/bin/bash
set -e

# Creates a pre-populated SQLite database for the Wails desktop app.
#
# The resulting file can be shipped alongside the Wails app so users
# do not need internet access for the initial ontology download.
#
# Pass --comprehensive to also load the extended ontology set (MONDO,
# UBERON, NCBI Taxonomy, PSI-MS, Cell Ontology, BTO, DOID).  NCBI
# Taxonomy alone adds ~2.7 M rows, making the file significantly larger.
#
# Output: dockerfiles/initial-wails.sqlite3
#
# The database contains one superuser:
#   username: cupcake_admin  /  password: ChangeMe123!
# Change this password after copying the file into a production install.

COMPREHENSIVE=false
for arg in "$@"; do
    if [ "$arg" = "--comprehensive" ]; then
        COMPREHENSIVE=true
    fi
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
OUT_FILE="$PROJECT_ROOT/dockerfiles/initial-wails.sqlite3"

WORK_DIR="$(mktemp -d)"
WAILS_USER_DATA="$WORK_DIR/cupcake-vanilla"
mkdir -p "$WAILS_USER_DATA"
DB_FILE="$WAILS_USER_DATA/cupcake_vanilla.db"

cleanup() {
    echo "Removing temporary work directory..."
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

export DJANGO_SETTINGS_MODULE="cupcake_vanilla.settings_wails"
export WAILS_APP_DATA="$WORK_DIR"
export DJANGO_SUPERUSER_USERNAME="cupcake_admin"
export DJANGO_SUPERUSER_PASSWORD="ChangeMe123!"
export DJANGO_SUPERUSER_EMAIL="admin@example.com"
export SECRET_KEY="temp-secret-key-for-initial-wails-db-generation"
export ENABLE_CUPCAKE_MACARON="true"
export ENABLE_CUPCAKE_MINT_CHOCOLATE="true"
export ENABLE_CUPCAKE_SALTED_CARAMEL="true"
export ENABLE_CUPCAKE_RED_VELVET="true"

cd "$PROJECT_ROOT"

RUN="poetry run python manage.py"

echo "Running migrations..."
$RUN migrate --noinput

echo "Creating initial superuser..."
$RUN createsuperuser --noinput

echo "Syncing built-in schemas..."
$RUN sync_schemas

echo "Loading standard column templates..."
$RUN load_column_templates --admin-user=cupcake_admin

echo "Loading core ontologies..."

echo "  - Species..."
$RUN load_species

echo "  - Tissue..."
$RUN load_tissue

echo "  - Human disease..."
$RUN load_human_disease

echo "  - MS modifications (Unimod)..."
$RUN load_ms_mod

echo "  - MS vocabulary terms..."
$RUN load_ms_term

echo "  - Subcellular locations..."
$RUN load_subcellular_location

if [ "$COMPREHENSIVE" = true ]; then
    echo "Loading comprehensive ontologies (--comprehensive flag set)..."

    echo "  - MONDO Disease Ontology..."
    $RUN load_ontologies --ontology mondo --no-limit

    echo "  - UBERON Anatomy..."
    $RUN load_ontologies --ontology uberon --no-limit

    echo "  - NCBI Taxonomy (large, may take several minutes)..."
    $RUN load_ontologies --ontology ncbi --no-limit

    echo "  - PSI-MS Ontology..."
    $RUN load_ontologies --ontology psims --no-limit

    echo "  - Cell Ontology..."
    $RUN load_ontologies --ontology cell --no-limit

    echo "  - BRENDA Tissue Ontology (BTO)..."
    $RUN load_ontologies --ontology bto --no-limit

    echo "  - Disease Ontology (DOID)..."
    $RUN load_ontologies --ontology doid --no-limit
else
    echo "Skipping comprehensive ontologies (pass --comprehensive to include MONDO, UBERON, NCBI, PSI-MS, CL, BTO, DOID)"
fi

echo "Verifying data..."
$RUN shell -c "
from ccv.models import (
    Species, Tissue, HumanDisease, SubcellularLocation,
    MSUniqueVocabularies, Unimod, MetadataColumnTemplate, Schema
)
from django.contrib.auth import get_user_model
User = get_user_model()

print('=== Initial Wails DB Data Counts ===')
print(f'Species:                  {Species.objects.count()}')
print(f'Tissue:                   {Tissue.objects.count()}')
print(f'Human Disease:            {HumanDisease.objects.count()}')
print(f'Subcellular Location:     {SubcellularLocation.objects.count()}')
print(f'MS Terms:                 {MSUniqueVocabularies.objects.count()}')
print(f'MS Modifications/Unimod:  {Unimod.objects.count()}')
print(f'Column Templates:         {MetadataColumnTemplate.objects.count()}')
print(f'Schemas:                  {Schema.objects.count()}')
print(f'Superuser (cupcake_admin): {User.objects.filter(username=\"cupcake_admin\", is_superuser=True).exists()}')
print('====================================')
"

if [ ! -f "$DB_FILE" ]; then
    echo "Error: SQLite database was not created at $DB_FILE"
    exit 1
fi

cp "$DB_FILE" "$OUT_FILE"

echo ""
echo "Done. Initial Wails SQLite database written to: $OUT_FILE"
echo "Size: $(du -h "$OUT_FILE" | cut -f1)"
echo ""
echo "WARNING: The database contains a superuser account:"
echo "  username: cupcake_admin / password: ChangeMe123!"
echo "  Change this password after deploying to any production install."
