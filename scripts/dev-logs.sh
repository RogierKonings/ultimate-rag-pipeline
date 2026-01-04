#!/bin/bash
# Follow logs for a specific service or all services
SERVICE=${1:-""}

if [ -z "$SERVICE" ]; then
    echo "📋 Following all service logs (Ctrl+C to stop)..."
    docker-compose logs -f
else
    echo "📋 Following logs for '$SERVICE' (Ctrl+C to stop)..."
    docker-compose logs -f "$SERVICE"
fi
