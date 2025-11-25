#!/bin/bash
set -e

echo "Creating prepopulated demo database dump..."

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DUMP_FILE="$PROJECT_ROOT/dockerfiles/demo-db-prepopulated.sql"

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

echo "Creating database backup using Django dbbackup..."
$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp python manage.py dbbackup

echo "Copying backup file to dockerfiles directory..."
BACKUP_FILE=$($DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp ls -t /app/backups/*.psql 2>/dev/null | head -1 | tr -d '\r')
if [ -z "$BACKUP_FILE" ]; then
    echo "Error: No backup file found!"
    exit 1
fi

$DOCKER_COMPOSE -f docker-compose.db-dump.yml exec -T web-temp cat "$BACKUP_FILE" > "$DUMP_FILE"

echo "Database dump created at: $DUMP_FILE"
echo "Dump size: $(du -h "$DUMP_FILE" | cut -f1)"

echo "Done! The prepopulated database dump is ready."
echo "This file will be copied into the Docker image and restored on each demo container start."
