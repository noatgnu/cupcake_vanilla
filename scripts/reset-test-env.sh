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
echo "Reset CUPCAKE Vanilla Test Environment"
echo "=========================================="
echo ""
echo "WARNING: This will delete all test data!"
echo "The environment will be restored from backup."
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Reset cancelled."
    exit 0
fi

echo ""
echo "Stopping services..."
docker-compose -f "$COMPOSE_FILE" down -v

echo ""
echo "Removing containers and volumes..."
echo "Done!"

echo ""
echo "Starting fresh environment..."
docker-compose -f "$COMPOSE_FILE" up -d

echo ""
echo "=========================================="
echo "Reset Complete"
echo "=========================================="
echo ""
echo "The test environment is being restored from backup."
echo "This may take 2-5 minutes."
echo ""
echo "Monitor progress with:"
echo "docker-compose -f ${COMPOSE_FILE} logs -f ${APP_CONTAINER}"
echo "=========================================="
