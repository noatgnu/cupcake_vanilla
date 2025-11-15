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
echo "Stopping CUPCAKE Vanilla Test Environment"
echo "=========================================="
echo ""

docker-compose -f "$COMPOSE_FILE" stop

echo ""
echo "Test environment stopped."
echo ""
echo "To start again:  ./scripts/start-test-env.sh"
echo "To remove data:  docker-compose -f ${COMPOSE_FILE} down -v"
echo "=========================================="
