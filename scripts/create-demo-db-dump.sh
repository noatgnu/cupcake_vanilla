#!/bin/bash
set -e

echo "Creating prepopulated demo database dump..."

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DUMP_FILE="$PROJECT_ROOT/dockerfiles/demo-db-prepopulated.psql.bin"

if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
    echo "Using docker-compose command..."
elif docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
    echo "Using docker compose plugin..."
else
    echo "Error: Neither 'docker-compose' nor 'docker compose' found!"
    exit 1
fi

cd "$PROJECT_ROOT"

cleanup() {
    echo "Cleaning up temporary containers..."
    $DOCKER_COMPOSE -f docker-compose.db-dump.yml down -v 2>/dev/null || true
}

trap cleanup EXIT

echo "Starting temporary environment with docker-compose..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml up -d postgres-temp redis-temp

echo "Waiting for services to be ready..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml up -d web-temp

echo "Running migrations..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py migrate --noinput

echo "Setting up demo mode..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py setup_demo_mode

echo "Loading reference data..."
echo "  - Syncing schemas..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py sync_schemas

echo "  - Loading column templates..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_column_templates

echo "  - Loading human disease ontology..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_human_disease

echo "  - Loading MS modification ontology..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_ms_mod

echo "  - Loading MS term ontology..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_ms_term

echo "  - Loading species ontology..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_species

echo "  - Loading subcellular location ontology..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_subcellular_location

echo "  - Loading tissue ontology..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_tissue

echo "Reference data loaded successfully!"

echo "Waiting for PostgreSQL to flush data to disk..."
sleep 5

echo "Verifying data exists before backup..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py shell -c "
from ccv.models import (
    Species, Tissue, HumanDisease, SubcellularLocation,
    MSUniqueVocabularies, Unimod, MetadataColumn, Schema
)
from django.contrib.auth import get_user_model
User = get_user_model()

print('=== Ontology Data Counts ===')
print(f'Species: {Species.objects.count()}')
print(f'Tissue: {Tissue.objects.count()}')
print(f'Human Disease: {HumanDisease.objects.count()}')
print(f'Subcellular Location: {SubcellularLocation.objects.count()}')
print(f'MS Terms: {MSUniqueVocabularies.objects.count()}')
print(f'MS Modifications (Unimod): {Unimod.objects.count()}')
print(f'Metadata Column Templates: {MetadataColumn.objects.count()}')
print(f'Schemas: {Schema.objects.count()}')
print(f'Demo user exists: {User.objects.filter(username=\"demo\").exists()}')
print('============================')
"

echo "Creating database backup using Django dbbackup..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py dbbackup --output-filename=demo-prepopulated.psql.bin

echo "Listing backup files..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp ls -lh /app/backups/

echo "Copying backup file to dockerfiles directory..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp cat /app/backups/demo-prepopulated.psql.bin > "$DUMP_FILE"

if [ ! -f "$DUMP_FILE" ] || [ ! -s "$DUMP_FILE" ]; then
    echo "Error: Backup file was not created or is empty!"
    exit 1
fi

echo "Database dump created at: $DUMP_FILE"
echo "Dump size: $(du -h "$DUMP_FILE" | cut -f1)"

echo "Done! The prepopulated database dump is ready."
echo "This file will be copied into the Docker image and restored on each demo container start."
