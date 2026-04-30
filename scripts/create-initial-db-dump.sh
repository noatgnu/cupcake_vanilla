#!/bin/bash
set -e

# Creates a pre-populated initial database dump containing:
#   - All tables from applied migrations
#   - Synced built-in schemas
#   - Standard metadata column templates
#   - Core ontology data (species, tissue, human disease, MS terms, MS
#     modifications, subcellular location)
#
# Pass --comprehensive to also load the extended ontology set (MONDO,
# UBERON, NCBI Taxonomy, PSI-MS, Cell Ontology, BTO, DOID).  ChEBI is
# excluded even in comprehensive mode because of its 250 MB download
# size; load it separately with:
#   python manage.py load_ontologies --ontology chebi
#
# The resulting dump is written to dockerfiles/initial-db.psql.bin and
# can be restored on a fresh instance without internet access via:
#   python manage.py dbrestore --input-filename initial-db.psql.bin
#
# The dump contains one superuser account:
#   username: cupcake_admin
#   password: ChangeMe123!
# Change this password immediately after restoring on a production instance.

COMPREHENSIVE=false
for arg in "$@"; do
    if [ "$arg" = "--comprehensive" ]; then
        COMPREHENSIVE=true
    fi
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DUMP_FILE="$PROJECT_ROOT/dockerfiles/initial-db.psql.bin"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.initial-dump.yml"

if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
elif docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    echo "Error: neither docker-compose nor docker compose found"
    exit 1
fi

cd "$PROJECT_ROOT"

cleanup() {
    echo "Cleaning up temporary containers..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" down -v 2>/dev/null || true
}
trap cleanup EXIT

echo "Cleaning up any existing containers..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" down -v 2>/dev/null || true
docker rmi $(docker images -q -f "label=com.docker.compose.project=cupcake_vanilla") 2>/dev/null || true

echo "Building web image (no cache)..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" build --no-cache --pull web-temp

echo "Starting services..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d postgres-temp redis-temp
$DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d web-temp

echo "Running migrations..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py migrate --noinput

echo "Creating initial superuser..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py createsuperuser \
    --noinput \
    --username=cupcake_admin \
    --email=admin@example.com

echo "Syncing built-in schemas..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py sync_schemas

echo "Loading standard column templates..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_column_templates \
    --admin-user=cupcake_admin

echo "Loading core ontologies..."

echo "  - Species..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_species

echo "  - Tissue..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_tissue

echo "  - Human disease..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_human_disease

echo "  - MS modifications (Unimod)..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ms_mod

echo "  - MS vocabulary terms..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ms_term

echo "  - Subcellular locations..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_subcellular_location

if [ "$COMPREHENSIVE" = true ]; then
    echo "Loading comprehensive ontologies (--comprehensive flag set)..."

    echo "  - MONDO Disease Ontology..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ontologies \
        --ontology mondo --no-limit

    echo "  - UBERON Anatomy..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ontologies \
        --ontology uberon --no-limit

    echo "  - NCBI Taxonomy (large download, may take several minutes)..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ontologies \
        --ontology ncbi --no-limit

    echo "  - PSI-MS Ontology..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ontologies \
        --ontology psims --no-limit

    echo "  - Cell Ontology..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ontologies \
        --ontology cell --no-limit

    echo "  - BRENDA Tissue Ontology (BTO)..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ontologies \
        --ontology bto --no-limit

    echo "  - Disease Ontology (DOID)..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py load_ontologies \
        --ontology doid --no-limit
else
    echo "Skipping comprehensive ontologies (pass --comprehensive to include MONDO, UBERON, NCBI, PSI-MS, CL, BTO, DOID)"
fi

echo "Waiting for PostgreSQL to flush..."
sleep 5

echo "Verifying data..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py shell -c "
from ccv.models import (
    Species, Tissue, HumanDisease, SubcellularLocation,
    MSUniqueVocabularies, Unimod, MetadataColumnTemplate, Schema
)
from django.contrib.auth import get_user_model
User = get_user_model()

print('=== Initial DB Data Counts ===')
print(f'Species:                  {Species.objects.count()}')
print(f'Tissue:                   {Tissue.objects.count()}')
print(f'Human Disease:            {HumanDisease.objects.count()}')
print(f'Subcellular Location:     {SubcellularLocation.objects.count()}')
print(f'MS Terms:                 {MSUniqueVocabularies.objects.count()}')
print(f'MS Modifications/Unimod:  {Unimod.objects.count()}')
print(f'Column Templates:         {MetadataColumnTemplate.objects.count()}')
print(f'Schemas:                  {Schema.objects.count()}')
print(f'Superuser (cupcake_admin): {User.objects.filter(username=\"cupcake_admin\", is_superuser=True).exists()}')
print('==============================')
"

echo "Creating database dump..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp python manage.py dbbackup \
    --output-filename=initial-db.psql.bin

echo "Copying dump to dockerfiles/..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T web-temp cat /app/backups/initial-db.psql.bin > "$DUMP_FILE"

if [ ! -f "$DUMP_FILE" ] || [ ! -s "$DUMP_FILE" ]; then
    echo "Error: dump file was not created or is empty"
    exit 1
fi

echo ""
echo "Done. Initial database dump written to: $DUMP_FILE"
echo "Size: $(du -h "$DUMP_FILE" | cut -f1)"
echo ""
echo "Restore on a new instance with:"
echo "  python manage.py dbrestore --input-filename initial-db.psql.bin"
echo ""
echo "WARNING: The dump contains a superuser account:"
echo "  username: cupcake_admin / password: ChangeMe123!"
echo "  Change this password immediately after restoring on any production instance."
