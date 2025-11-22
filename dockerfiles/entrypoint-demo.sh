#!/bin/bash
set -e

DUMP_FILE="/demo-db-prepopulated.sql"

if [ -f "$DUMP_FILE" ]; then
    echo "Found prepopulated database dump - restoring..."

    echo "Waiting for PostgreSQL to be ready..."
    until PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d postgres -c '\q' 2>/dev/null; do
        echo "  PostgreSQL is unavailable - waiting..."
        sleep 2
    done

    echo "Restoring database from dump..."
    PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$DUMP_FILE"

    echo "Database restored successfully!"
    echo "Setting up demo mode..."
    python manage.py setup_demo_mode

else
    echo "No prepopulated database dump found - loading data from commands..."
    echo "Running migrations..."
    python manage.py migrate --noinput

    echo "Setting up demo mode..."
    python manage.py setup_demo_mode

    echo "Loading reference data..."
    echo "  - Syncing schemas..."
    python manage.py sync_schemas

    echo "  - Loading column templates..."
    python manage.py load_column_templates

    echo "  - Loading human disease ontology..."
    python manage.py load_human_disease

    echo "  - Loading MS modification ontology..."
    python manage.py load_ms_mod

    echo "  - Loading MS term ontology..."
    python manage.py load_ms_term

    echo "  - Loading species ontology..."
    python manage.py load_species

    echo "  - Loading subcellular location ontology..."
    python manage.py load_subcellular_location

    echo "  - Loading tissue ontology..."
    python manage.py load_tissue

    echo "Reference data loaded successfully."
fi

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting application..."
exec "$@"
