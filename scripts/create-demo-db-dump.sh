#!/bin/bash
set -e

echo "Creating prepopulated demo database dump..."

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DUMP_FILE="$PROJECT_ROOT/dockerfiles/demo-db-prepopulated.sql"

TEMP_CONTAINER="cupcake_demo_db_temp_$$"
TEMP_DB="cupcake_demo_temp"
TEMP_USER="cupcake_temp"
TEMP_PASSWORD="cupcake_temp_pass"

cleanup() {
    echo "Cleaning up temporary container..."
    docker rm -f "$TEMP_CONTAINER" 2>/dev/null || true
}

trap cleanup EXIT

if command -v poetry &> /dev/null; then
    PYTHON_CMD="poetry run python"
    echo "Using poetry to run commands..."
else
    PYTHON_CMD="python"
    echo "Poetry not found, using system python..."
fi

echo "Starting temporary PostgreSQL container..."
docker run -d \
    --name "$TEMP_CONTAINER" \
    -p 5432 \
    -e POSTGRES_DB="$TEMP_DB" \
    -e POSTGRES_USER="$TEMP_USER" \
    -e POSTGRES_PASSWORD="$TEMP_PASSWORD" \
    postgres:16

echo "Waiting for PostgreSQL to be ready..."
sleep 5

until docker exec "$TEMP_CONTAINER" pg_isready -U "$TEMP_USER" > /dev/null 2>&1; do
    echo "  Waiting for database..."
    sleep 2
done

echo "PostgreSQL is ready!"

export POSTGRES_DB="$TEMP_DB"
export POSTGRES_USER="$TEMP_USER"
export POSTGRES_PASSWORD="$TEMP_PASSWORD"
export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT=$(docker port "$TEMP_CONTAINER" 5432 | cut -d: -f2)

export SECRET_KEY="temp-secret-key-for-db-generation"
export DEBUG="False"
export DEMO_MODE="True"
export ALLOWED_HOSTS="localhost"
export CORS_ORIGIN_WHITELIST="http://localhost:4200"

export REDIS_HOST="localhost"
export REDIS_PORT="6379"
export REDIS_URL="redis://localhost:6379/1"
export REDIS_DB_RQ="3"

export ENABLE_CUPCAKE_MACARON="True"
export ENABLE_CUPCAKE_MINT_CHOCOLATE="False"
export ENABLE_CUPCAKE_RED_VELVET="True"
export ENABLE_CUPCAKE_SALTED_CARAMEL="True"
export USE_WHISPER="False"

cd "$PROJECT_ROOT"

echo "Running migrations..."
$PYTHON_CMD manage.py migrate --noinput

echo "Loading reference data..."
echo "  - Syncing schemas..."
$PYTHON_CMD manage.py sync_schemas

echo "  - Loading column templates..."
$PYTHON_CMD manage.py load_column_templates

echo "  - Loading human disease ontology..."
$PYTHON_CMD manage.py load_human_disease

echo "  - Loading MS modification ontology..."
$PYTHON_CMD manage.py load_ms_mod

echo "  - Loading MS term ontology..."
$PYTHON_CMD manage.py load_ms_term

echo "  - Loading species ontology..."
$PYTHON_CMD manage.py load_species

echo "  - Loading subcellular location ontology..."
$PYTHON_CMD manage.py load_subcellular_location

echo "  - Loading tissue ontology..."
$PYTHON_CMD manage.py load_tissue

echo "Reference data loaded successfully!"

echo "Creating database dump..."
docker exec "$TEMP_CONTAINER" pg_dump -U "$TEMP_USER" -d "$TEMP_DB" --clean --if-exists > "$DUMP_FILE"

echo "Database dump created at: $DUMP_FILE"
echo "Dump size: $(du -h "$DUMP_FILE" | cut -f1)"

echo "Done! The prepopulated database dump is ready."
echo "This file will be copied into the Docker image and restored on each demo container start."
