#!/bin/bash

# Build script for CUPCAKE Vanilla Frontend with Docker Compose

set -e

# Default hostname
HOSTNAME=${1:-ccv.ome.quest}

echo "🚀 Building CUPCAKE Vanilla Frontend for hostname: $HOSTNAME"

# Set build args
export HOSTNAME=$HOSTNAME

# Build only the frontend service (faster if backend hasn't changed)
echo "📦 Building frontend Docker image..."
docker-compose -f docker-compose.ccv.yml build frontend

echo "🔄 Rebuilding nginx to use updated configuration..."
docker-compose -f docker-compose.ccv.yml build nginx

echo "✅ Build complete! Run the following to start the services:"
echo ""
echo "# For full stack (first time or backend changes):"
echo "docker-compose -f docker-compose.ccv.yml up -d"
echo ""
echo "# For frontend-only restart (if backend is already running):"
echo "docker-compose -f docker-compose.ccv.yml up -d frontend nginx"
echo ""
echo "# To view logs:"
echo "docker-compose -f docker-compose.ccv.yml logs -f frontend"
echo ""
echo "🌐 Frontend will be available at: https://$HOSTNAME"
echo "📡 API will be available at: https://$HOSTNAME/api/v1/"
echo "⚙️  Admin will be available at: https://$HOSTNAME/admin/"
