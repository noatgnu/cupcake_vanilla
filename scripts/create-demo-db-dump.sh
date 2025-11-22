#!/bin/bash
set -e

echo "Creating prepopulated demo database dump..."

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DUMP_FILE="$PROJECT_ROOT/dockerfiles/demo-db-prepopulated.sql"

cd "$PROJECT_ROOT"

cleanup() {
    echo "Cleaning up temporary containers..."
    docker-compose -f docker-compose.db-dump.yml down -v 2>/dev/null || true
}

trap cleanup EXIT

echo "Starting temporary environment with docker-compose..."
docker-compose -f docker-compose.db-dump.yml up -d postgres-temp redis-temp

echo "Waiting for services to be ready..."
docker-compose -f docker-compose.db-dump.yml up -d web-temp

echo "Running migrations..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py migrate --noinput

echo "Setting up demo mode..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py setup_demo_mode

echo "Loading reference data..."
echo "  - Syncing schemas..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py sync_schemas

echo "  - Loading column templates..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_column_templates

echo "  - Loading human disease ontology..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_human_disease

echo "  - Loading MS modification ontology..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_ms_mod

echo "  - Loading MS term ontology..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_ms_term

echo "  - Loading species ontology..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_species

echo "  - Loading subcellular location ontology..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_subcellular_location

echo "  - Loading tissue ontology..."
docker-compose -f docker-compose.db-dump.yml exec -T web-temp python manage.py load_tissue

echo "Reference data loaded successfully!"

echo "Creating database dump..."
docker-compose -f docker-compose.db-dump.yml exec -T postgres-temp pg_dump -U cupcake_dump -d cupcake_dump_temp --clean --if-exists > "$DUMP_FILE"

echo "Database dump created at: $DUMP_FILE"
echo "Dump size: $(du -h "$DUMP_FILE" | cut -f1)"

echo "Done! The prepopulated database dump is ready."
echo "This file will be copied into the Docker image and restored on each demo container start."
