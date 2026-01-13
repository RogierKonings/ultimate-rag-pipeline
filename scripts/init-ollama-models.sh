#!/bin/bash
# Initialize Ollama with recommended models for local development
# Run after `make up-all` to pull models

set -e

CONTAINER="rag-ollama"
DEFAULT_MODEL="${LLM_MODEL:-llama3.1:8b}"

echo "=== Ollama Model Initialization ==="
echo ""

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
until docker exec "$CONTAINER" ollama list &>/dev/null; do
    sleep 2
done
echo "Ollama is ready."
echo ""

# Pull the default model
echo "Pulling default model: $DEFAULT_MODEL"
docker exec "$CONTAINER" ollama pull "$DEFAULT_MODEL"
echo ""

# List installed models
echo "Installed models:"
docker exec "$CONTAINER" ollama list

echo ""
echo "=== Setup complete ==="
echo "Test with: make test-llm"
