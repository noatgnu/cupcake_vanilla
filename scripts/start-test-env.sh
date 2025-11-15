#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$PROJECT_ROOT/.env.test" ]; then
    source "$PROJECT_ROOT/.env.test"
else
    echo "ERROR: .env.test file not found!"
    echo "Expected: $PROJECT_ROOT/.env.test"
    exit 1
fi

cd "$PROJECT_ROOT"

echo "=========================================="
echo "CUPCAKE Vanilla Test Environment"
echo "=========================================="
echo ""

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "ERROR: ${COMPOSE_FILE} not found!"
    echo "Please run this script from the project root directory."
    exit 1
fi

if [ ! -f "${BACKUP_DIR}/${DB_BACKUP_FILE}" ]; then
    echo "ERROR: Database backup not found!"
    echo "Expected: ${BACKUP_DIR}/${DB_BACKUP_FILE}"
    exit 1
fi

if [ ! -f "${BACKUP_DIR}/${MEDIA_BACKUP_FILE}" ]; then
    echo "ERROR: Media backup not found!"
    echo "Expected: ${BACKUP_DIR}/${MEDIA_BACKUP_FILE}"
    exit 1
fi

echo "Starting test environment..."
echo ""

docker-compose -f "$COMPOSE_FILE" up -d

echo ""
echo "Waiting for services to start..."
sleep "$STARTUP_WAIT_TIME"

echo ""
echo "=========================================="
echo "Test Environment Status"
echo "=========================================="
docker-compose -f "$COMPOSE_FILE" ps
echo ""

echo "=========================================="
echo "Service URLs"
echo "=========================================="
echo "API:        ${API_URL}"
echo "Admin:      ${ADMIN_URL}"
echo "Database:   ${DB_URL}"
echo "Redis:      ${REDIS_URL}"
echo ""

echo "=========================================="
echo "Quick Commands"
echo "=========================================="
echo "View logs:          docker-compose -f ${COMPOSE_FILE} logs -f"
echo "Stop:               docker-compose -f ${COMPOSE_FILE} stop"
echo "Restart:            docker-compose -f ${COMPOSE_FILE} restart"
echo "Full reset:         docker-compose -f ${COMPOSE_FILE} down -v"
echo "Create superuser:   docker-compose -f ${COMPOSE_FILE} exec ${APP_CONTAINER} python manage.py createsuperuser"
echo ""

echo "=========================================="
echo "Initialization"
echo "=========================================="
echo "The database is being restored from backup."
echo "This may take 2-5 minutes on first startup."
echo ""
echo "Monitor progress with:"
echo "docker-compose -f ${COMPOSE_FILE} logs -f ${APP_CONTAINER}"
echo ""
echo "Once you see 'Starting Django server...', the API is ready!"
echo "=========================================="
