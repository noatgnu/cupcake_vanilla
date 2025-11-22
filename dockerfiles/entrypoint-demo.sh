#!/bin/bash
set -e

echo "Running migrations..."
python manage.py migrate --noinput

echo "Setting up demo mode..."
python manage.py setup_demo_mode

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Daphne (handles both HTTP and WebSocket)..."
daphne -b 127.0.0.1 -p 8001 cupcake_vanilla.asgi:application &

echo "Starting nginx..."
nginx -g 'daemon off;'
